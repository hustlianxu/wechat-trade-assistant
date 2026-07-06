"""自动检测与自动解密：启动时傻瓜式配置。

设计原则：
- 所有路径自动检测，用户无需手工填写
- 检测顺序：环境变量 → wechat-decrypt 项目目录 → 微信默认安装位置 → 常见安装路径
- macOS 上密钥提取需 sudo + 重签名，无法 100% 自动；但若 all_keys.json 已存在，
  可自动调用 decrypt_db.py -i 增量解密
- 检测到的配置自动写回 ~/.wta_ui/config.json

调用入口：
    from auto_setup import run_auto_setup
    result = run_auto_setup()  # 返回 {decrypted_dir, self_wxid, whisper, ...}
"""

from __future__ import annotations

import glob
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ============================================================================
# 路径常量
# ============================================================================
_SYSTEM = platform.system().lower()
IS_MACOS = _SYSTEM == "darwin"
IS_WINDOWS = _SYSTEM == "windows"
IS_LINUX = _SYSTEM == "linux"


def _wechat_decrypt_dir_candidates() -> list[Path]:
    """查找 wechat-decrypt 项目目录的候选列表（含 decrypt_db.py 的目录）。

    顺序：
    1. 环境变量 WECHAT_DECRYPT_DIR
    2. wechat-ui 同级目录下的 wechat-decrypt / wechat-decrypt-ref
    3. 当前工作目录的上级目录
    4. ~/wechat-decrypt
    """
    candidates: list[Path] = []

    # 1. 环境变量
    env = os.environ.get("WECHAT_DECRYPT_DIR", "")
    if env:
        p = Path(env)
        if (p / "decrypt_db.py").exists():
            candidates.append(p)

    # 2. wechat-ui 同级目录
    # 本文件位于 wechat-ui/backend/auto_setup.py，向上 3 级是项目根
    here = Path(__file__).resolve().parent
    for up in (here.parent, here.parent.parent, here.parent.parent.parent):
        for sub in ("wechat-decrypt", "wechat-decrypt-ref"):
            p = up / sub
            if (p / "decrypt_db.py").exists():
                candidates.append(p)

    # 3. 当前工作目录的上级
    cwd = Path.cwd()
    for up in (cwd, cwd.parent, cwd.parent.parent):
        for sub in ("wechat-decrypt", "wechat-decrypt-ref"):
            p = up / sub
            if (p / "decrypt_db.py").exists():
                candidates.append(p)

    # 4. 家目录
    home = Path.home()
    for sub in ("wechat-decrypt", "wechat-decrypt-ref", "Documents/wechat-decrypt"):
        p = home / sub
        if (p / "decrypt_db.py").exists():
            candidates.append(p)

    # 5. 常见开发目录：~/Study/、~/Projects/、~/code/ 等
    for dev_name in ("Study", "Projects", "code", "workspace", "work", "dev",
                     "repos", "src", "github", "Code"):
        dev_dir = home / dev_name
        if not dev_dir.is_dir():
            continue
        for sub in ("wechat-decrypt", "wechat-decrypt-ref", "wechat_decrypt"):
            p = dev_dir / sub
            if (p / "decrypt_db.py").exists():
                candidates.append(p)

    # 去重
    seen = set()
    result = []
    for c in candidates:
        key = str(c.resolve())
        if key not in seen:
            seen.add(key)
            result.append(c)
    return result


def find_wechat_decrypt_dir() -> Optional[Path]:
    """找到 wechat-decrypt 项目目录。"""
    for c in _wechat_decrypt_dir_candidates():
        if c.exists():
            return c
    return None


def load_wcd_config() -> dict:
    """加载 wechat-decrypt 的 config.json（已自动检测 db_dir 并展开绝对路径）。"""
    wcd_dir = find_wechat_decrypt_dir()
    if wcd_dir is None:
        return {}
    config_file = wcd_dir / "config.json"
    if not config_file.exists():
        return {}

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # 展开相对路径为绝对路径（wechat-decrypt 的相对路径基于其项目目录）
    base = wcd_dir
    for key in ("keys_file", "decrypted_dir", "decoded_image_dir"):
        v = cfg.get(key, "")
        if v and not os.path.isabs(v):
            cfg[key] = str((base / v).resolve())
    # db_dir
    db_dir = cfg.get("db_dir", "")
    if db_dir and not os.path.isabs(db_dir):
        cfg["db_dir"] = str((base / db_dir).resolve())
    return cfg


# ============================================================================
# 自动检测微信数据目录
# ============================================================================
def auto_detect_wechat_data_dir() -> Optional[str]:
    """自动检测微信数据目录（db_storage 的父目录，即 xwechat_files/<wxid>）。

    优先调用 wechat-decrypt 的 auto_detect_db_dir（更精准），
    回退到本地实现的常见路径扫描。
    """
    # 1. 优先用 wechat-decrypt 的检测逻辑
    wcd_dir = find_wechat_decrypt_dir()
    if wcd_dir is not None:
        try:
            # 把 wechat-decrypt 目录加入 sys.path，import 它的 config
            wcd_str = str(wcd_dir)
            if wcd_str not in sys.path:
                sys.path.insert(0, wcd_str)
            # 设置非交互模式，避免卡在输入
            os.environ.setdefault("WECHAT_DECRYPT_NONINTERACTIVE", "1")
            from config import auto_detect_db_dir  # type: ignore
            db_dir = auto_detect_db_dir()
            if db_dir and os.path.isdir(db_dir):
                # db_dir 形如 .../xwechat_files/<wxid>/db_storage
                # 父目录是账号目录
                return str(Path(db_dir).parent)
        except Exception as e:
            print(f"[auto_setup] 调用 wechat-decrypt 检测失败：{e}", file=sys.stderr)

    # 2. 回退：扫描常见路径
    return _scan_common_wechat_dirs()


def _scan_common_wechat_dirs() -> Optional[str]:
    """扫描常见微信数据目录位置。"""
    home = Path.home()
    candidates: list[Path] = []

    if IS_MACOS:
        # macOS 4.x 标准路径
        base = home / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
        if base.exists():
            for sub in base.iterdir():
                db_storage = sub / "db_storage"
                if db_storage.is_dir():
                    candidates.append(sub)
        # 兜底：Group Containers
        gc = home / "Library/Group Containers"
        if gc.is_dir():
            for sub in gc.iterdir():
                if "tencent" in sub.name.lower() and sub.is_dir():
                    for acct in sub.rglob("db_storage"):
                        if acct.parent not in candidates:
                            candidates.append(acct.parent)
    elif IS_WINDOWS:
        for env_var in ("APPDATA", "LOCALAPPDATA"):
            base = Path(os.environ.get(env_var, "")) / "Tencent/xwechat_files"
            if base.exists():
                for sub in base.iterdir():
                    db_storage = sub / "db_storage"
                    if db_storage.is_dir():
                        candidates.append(sub)
    elif IS_LINUX:
        base = home / "Documents/xwechat_files"
        if base.exists():
            for sub in base.iterdir():
                db_storage = sub / "db_storage"
                if db_storage.is_dir():
                    candidates.append(sub)

    if not candidates:
        return None

    # 多账号：选最近活跃的（按 message 子目录 mtime 排序）
    def _account_mtime(p: Path) -> float:
        msg_dir = p / "db_storage" / "message"
        if msg_dir.is_dir():
            try:
                return max(f.stat().st_mtime for f in msg_dir.glob("*.db"))
            except (OSError, ValueError):
                pass
        return 0.0

    candidates.sort(key=_account_mtime, reverse=True)
    return str(candidates[0])


# ============================================================================
# 自动检测 self_wxid
# ============================================================================
def auto_detect_self_wxid(wechat_data_dir: str = "", decrypted_dir: str = "") -> Optional[str]:
    """自动检测本人 wxid。

    优先级：
    1. 从 wechat_data_dir 的目录名提取（xwechat_files/<wxid>/db_storage）
    2. 从 decrypted_dir/contact.db 找（最近发送消息最多且 local_type=1 的）
    3. 从 session.db 找发送方最活跃的
    """
    # 1. 从数据目录名提取
    if wechat_data_dir:
        wxid = Path(wechat_data_dir).name
        # 4.x 账号目录名就是 wxid
        if wxid and wxid != "db_storage" and not wxid.startswith("."):
            # 校验：不应是中文名（4.x wxid 通常是 wxid_xxx 或纯字母数字）
            if _looks_like_wxid(wxid):
                return wxid

    # 2. 从 contact.db 推断（找消息表里 real_sender_id 对应的 Name2Id.user_name）
    if decrypted_dir:
        wxid = _infer_self_from_decrypted(decrypted_dir)
        if wxid:
            return wxid

    return None


def _looks_like_wxid(s: str) -> bool:
    """判断字符串是否像 wxid 格式。"""
    if not s or len(s) < 4 or len(s) > 64:
        return False
    # wxid 通常以 wxid_ 开头，或是纯字母数字下划线
    if s.startswith("wxid_"):
        return True
    # 排除明显非 wxid 的（含中文、空格等）
    if any(ord(c) > 127 for c in s):
        return False
    return all(c.isalnum() or c in "_-@" for c in s)


def _infer_self_from_decrypted(decrypted_dir: str) -> Optional[str]:
    """从解密后的数据库推断本人 wxid。

    策略：扫描所有 message_N.db，统计 Name2Id 表里每个 user_name 作为 real_sender_id
    出现的次数，出现最多的就是本人（因为本人发的消息也很多）。
    更精准的做法：找 session.db 里 last_msg_type=1 且 summary 内容匹配自己发出去的特征。
    简化：找 message 表里 is_self_send 候选中，发送频次最高的。
    """
    base = Path(decrypted_dir)
    if not base.exists():
        return None

    # 统计每个 sender 在所有消息表中的出现次数
    sender_count: dict[str, int] = {}

    # 找所有 message_N.db
    msg_dbs = list(base.rglob("message_*.db"))
    msg_dbs = [p for p in msg_dbs if "fts" not in p.name and "resource" not in p.name
               and "media" not in p.name and "biz" not in p.name]

    for db_path in msg_dbs[:3]:  # 只看前 3 个分片，够推断
        try:
            conn = sqlite3.connect(str(db_path))
            # 获取 Name2Id 映射
            name2id: dict[int, str] = {}
            try:
                for row in conn.execute("SELECT rowid, user_name FROM Name2Id").fetchall():
                    name2id[row[0]] = row[1] or ""
            except sqlite3.Error:
                conn.close()
                continue

            # 统计每个 sender_id 出现次数
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
            ).fetchall()
            for (table_name,) in tables[:5]:  # 每个分片看前 5 个会话
                try:
                    for row in conn.execute(
                        f'SELECT real_sender_id, COUNT(*) FROM "{table_name}" GROUP BY real_sender_id'
                    ).fetchall():
                        sid, cnt = row[0], row[1]
                        uname = name2id.get(sid, "")
                        if uname:
                            sender_count[uname] = sender_count.get(uname, 0) + cnt
                except sqlite3.Error:
                    continue
            conn.close()
        except sqlite3.Error:
            continue

    if not sender_count:
        return None

    # 出现次数最多的视为本人（在所有会话里都活跃的）
    sorted_senders = sorted(sender_count.items(), key=lambda x: x[1], reverse=True)
    return sorted_senders[0][0]


# ============================================================================
# 自动检测已存在的 decrypted 目录
# ============================================================================
# 常见开发目录：用户常把 wechat-decrypt 克隆在这些目录下，解密结果也在其中
_DEV_DIR_NAMES = ("Study", "Projects", "code", "workspace", "work", "dev",
                  "repos", "src", "github", "Code")

# wechat-decrypt 可能的目录名（解密结果常在其下的 decrypted/ 子目录）
_WCD_DIR_NAMES = ("wechat-decrypt", "wechat-decrypt-ref", "wechat_decrypt")


def _dev_dir_candidates() -> list[Path]:
    """返回需要扫描的开发目录候选列表（家目录下 + 常见绝对路径）。

    覆盖 ~/Study/、~/Projects/、~/code/ 等开发者常放代码的位置。
    """
    candidates: list[Path] = []
    home = Path.home()

    # 1. 家目录下的常见开发目录
    for name in _DEV_DIR_NAMES:
        p = home / name
        if p.is_dir():
            candidates.append(p)

    # 2. 家目录本身（用户可能直接把 wechat-decrypt 放在 ~ 下）
    candidates.append(home)

    # 3. 常见绝对路径（macOS / Linux）
    for abs_path in ("/opt", "/srv"):
        p = Path(abs_path)
        if p.is_dir():
            candidates.append(p)

    return candidates


def _scan_dev_dirs_for_decrypted() -> Optional[str]:
    """扫描开发目录下的 wechat-decrypt 项目及其 decrypted/ 子目录。

    查找模式：
    - ~/Study/wechat-decrypt/decrypted
    - ~/Projects/wechat-decrypt/decrypted
    - ~/code/wechat-decrypt/decrypted
    - 以及 wechat-decrypt-ref 等变体
    - 也直接查找 ~/Study/decrypted 等直接放在开发目录下的情况
    """
    for dev_dir in _dev_dir_candidates():
        # 1. dev_dir/<wcd_name>/decrypted
        for wcd_name in _WCD_DIR_NAMES:
            p = dev_dir / wcd_name / "decrypted"
            if _is_valid_decrypted_dir(p):
                return str(p)
        # 2. dev_dir/decrypted（直接放在开发目录下）
        p = dev_dir / "decrypted"
        if _is_valid_decrypted_dir(p):
            return str(p)
        # 3. dev_dir/wechat-decrypt/<wcd_name>/decrypted（嵌套一层）
        for wcd_name in _WCD_DIR_NAMES:
            nested = dev_dir / "wechat-decrypt" / wcd_name / "decrypted"
            if _is_valid_decrypted_dir(nested):
                return str(nested)
    return None


def auto_detect_decrypted_dir() -> Optional[str]:
    """自动检测已存在的解密目录。

    顺序：
    1. wechat-decrypt 的 config.json 中 decrypted_dir（已展开绝对路径）
    2. wechat-decrypt 项目目录下的 decrypted/
    3. wechat-ui 同级目录下的 decrypted/
    4. 开发目录扫描：~/Study/、~/Projects/、~/code/ 等下的 wechat-decrypt/decrypted
    5. ~/.wta_ui/decrypted/
    6. /tmp/wechat_decrypted/（mcp_server 缓存）
    """
    # 1. wechat-decrypt config.json
    wcd_cfg = load_wcd_config()
    decrypted = wcd_cfg.get("decrypted_dir", "")
    if decrypted and os.path.isdir(decrypted):
        # 验证目录结构：至少有 contact 或 message 子目录
        if _is_valid_decrypted_dir(decrypted):
            return decrypted

    # 2. wechat-decrypt 项目目录下的 decrypted/
    wcd_dir = find_wechat_decrypt_dir()
    if wcd_dir is not None:
        p = wcd_dir / "decrypted"
        if _is_valid_decrypted_dir(p):
            return str(p)

    # 3. wechat-ui 同级目录
    here = Path(__file__).resolve().parent.parent  # wechat-ui/
    for up in (here, here.parent, here.parent.parent):
        p = up / "decrypted"
        if _is_valid_decrypted_dir(p):
            return str(p)

    # 4. 开发目录扫描：~/Study/、~/Projects/、~/code/ 等
    dev_hit = _scan_dev_dirs_for_decrypted()
    if dev_hit:
        return dev_hit

    # 5. ~/.wta_ui/decrypted/
    p = Path.home() / ".wta_ui" / "decrypted"
    if _is_valid_decrypted_dir(p):
        return str(p)

    # 6. 临时缓存
    p = Path("/tmp/wechat_decrypted")
    if _is_valid_decrypted_dir(p):
        return str(p)

    return None


def _is_valid_decrypted_dir(p) -> bool:
    """检查目录是否包含解密后的微信数据库结构。"""
    p = Path(p)
    if not p.is_dir():
        return False
    # 至少有 contact.db 或 message_*.db 之一
    has_contact = any(p.rglob("contact.db")) or any(p.rglob("wccontact_new2.db"))
    has_msg = any(p.rglob("message_*.db")) or any(p.rglob("msg_*.db"))
    return has_contact or has_msg


# ============================================================================
# 自动调用增量解密
# ============================================================================
def try_auto_decrypt(timeout: int = 300) -> dict:
    """如果有 all_keys.json，自动调用 decrypt_db.py -i 增量解密。

    返回：
        {
            "success": bool,
            "message": str,
            "decrypted_dir": str | None,
            "decrypted_count": int,
        }
    """
    wcd_dir = find_wechat_decrypt_dir()
    if wcd_dir is None:
        return {
            "success": False,
            "message": "未找到 wechat-decrypt 项目目录。请克隆 https://github.com/xMduo/wechat-decrypt 并配置环境变量 WECHAT_DECRYPT_DIR",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }

    # 检查 all_keys.json 是否存在
    wcd_cfg = load_wcd_config()
    keys_file = wcd_cfg.get("keys_file", "")
    if not keys_file or not os.path.isfile(keys_file):
        # 兜底：项目目录下的 all_keys.json
        alt_keys = wcd_dir / "all_keys.json"
        if alt_keys.exists():
            keys_file = str(alt_keys)
        else:
            if IS_MACOS:
                return {
                    "success": False,
                    "message": (
                        "未找到密钥文件 all_keys.json。macOS 上需要先执行：\n"
                        "  1. killall WeChat\n"
                        "  2. sudo codesign --force --deep --sign - /Applications/WeChat.app\n"
                        "  3. 启动微信并登录\n"
                        f"  4. cd {wcd_dir} && cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation\n"
                        "  5. sudo ./find_all_keys_macos\n"
                        "完成后回来重试自动解密。"
                    ),
                    "decrypted_dir": None,
                    "decrypted_count": 0,
                }
            return {
                "success": False,
                "message": f"未找到密钥文件 all_keys.json（预期位置：{keys_file}）",
                "decrypted_dir": None,
                "decrypted_count": 0,
            }

    # 检查 db_dir 是否存在
    db_dir = wcd_cfg.get("db_dir", "")
    if not db_dir or not os.path.isdir(db_dir):
        return {
            "success": False,
            "message": f"微信数据目录不存在：{db_dir}。请确认微信已安装并登录过。",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }

    # 调用 decrypt_db.py -i 增量解密
    decrypt_script = wcd_dir / "decrypt_db.py"
    if not decrypt_script.exists():
        return {
            "success": False,
            "message": f"未找到解密脚本：{decrypt_script}",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }

    try:
        # 设置非交互模式，cd 到 wechat-decrypt 目录执行
        env = os.environ.copy()
        env["WECHAT_DECRYPT_NONINTERACTIVE"] = "1"
        result = subprocess.run(
            [sys.executable, "decrypt_db.py", "-i"],
            cwd=str(wcd_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        # 解析输出找解密数量和目录
        output = result.stdout + result.stderr
        decrypted_count = _parse_decrypt_count(output)

        # 解密后的目录
        decrypted_dir = wcd_cfg.get("decrypted_dir", "")
        if not decrypted_dir or not os.path.isdir(decrypted_dir):
            decrypted_dir = str(wcd_dir / "decrypted")

        if result.returncode == 0 or _is_valid_decrypted_dir(decrypted_dir):
            return {
                "success": True,
                "message": f"解密成功（增量模式，{decrypted_count} 个数据库）",
                "decrypted_dir": decrypted_dir,
                "decrypted_count": decrypted_count,
            }
        return {
            "success": False,
            "message": f"解密失败（退出码 {result.returncode}）：\n{output[-500:]}",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": f"解密超时（{timeout}秒）",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"解密异常：{e}",
            "decrypted_dir": None,
            "decrypted_count": 0,
        }


def _parse_decrypt_count(output: str) -> int:
    """从 decrypt_db.py 输出中解析解密成功的数据库数量。"""
    import re
    # decrypt_db.py 输出形如："解密成功: 26 个数据库"
    m = re.search(r"(?:解密成功|decrypted|success)[:\s]*(\d+)", output, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # 兜底：数 "✓" 或 "[OK]" 标记
    return output.count("✓") + output.count("[OK]")


# ============================================================================
# 自动检测 whisper.cpp
# ============================================================================
def auto_detect_whisper() -> dict:
    """自动检测 whisper.cpp 安装位置。

    返回：
        {
            "binary_path": str,
            "model_path": str,
            "language": str,  # 默认空（自动检测）
        }
    """
    binary_path = ""
    model_path = ""

    # 1. PATH 中查找 whisper-cpp / whisper-cli
    for name in ("whisper-cpp", "whisper-cli", "whisper"):
        p = shutil.which(name)
        if p:
            binary_path = p
            break

    # 2. macOS Homebrew 路径
    if not binary_path and IS_MACOS:
        for prefix in ("/opt/homebrew", "/usr/local"):
            p = Path(prefix) / "bin" / "whisper-cpp"
            if p.exists():
                binary_path = str(p)
                break

    # 3. Linux 常见路径
    if not binary_path and IS_LINUX:
        for p in ("/usr/local/bin/whisper-cpp", "/usr/bin/whisper-cpp"):
            if os.path.isfile(p):
                binary_path = p
                break

    # 4. 项目本地 bin/
    if not binary_path:
        here = Path(__file__).resolve().parent.parent
        for sub in ("bin", "../bin"):
            p = here / sub / "whisper-cpp"
            if p.exists():
                binary_path = str(p)
                break

    # 检测模型
    model_candidates = []
    if IS_MACOS:
        for prefix in ("/opt/homebrew", "/usr/local"):
            model_candidates.extend([
                Path(prefix) / "share/whisper-cpp/ggml-large-v3.bin",
                Path(prefix) / "share/whisper-cpp/ggml-large.bin",
                Path(prefix) / "share/whisper-cpp/ggml-medium.bin",
                Path(prefix) / "share/whisper-cpp/ggml-base.bin",
                Path(prefix) / "share/whisper-cpp/ggml-small.bin",
            ])
    # 项目本地 models/
    here = Path(__file__).resolve().parent.parent
    for sub in ("models", "../models", "models/whisper"):
        d = here / sub
        if d.is_dir():
            for f in d.glob("*.bin") + d.glob("*.gguf"):
                model_candidates.append(f)

    for m in model_candidates:
        if m.exists() and m.stat().st_size > 1_000_000:  # >1MB
            model_path = str(m)
            break

    return {
        "binary_path": binary_path,
        "model_path": model_path,
        # 默认空，让 whisper 自动检测；外贸场景可设 "es"
        "language": "",
    }


# ============================================================================
# 总入口：一键自动配置
# ============================================================================
def run_auto_setup(force: bool = False) -> dict:
    """一键自动检测并补全所有配置。

    Args:
        force: True 表示强制重新检测，即使现有配置看起来完整

    Returns:
        {
            "decrypted_dir": str,
            "wechat_base_dir": str,
            "self_wxid": str,
            "whisper": {...},
            "auto_setup_status": "ok" | "partial" | "failed",
            "messages": [str, ...],  # 检测过程的提示信息
            "needs_manual_action": str | None,  # 需要用户手动操作的提示
        }
    """
    messages: list[str] = []
    needs_manual: Optional[str] = None

    # 1. 检测已存在的 decrypted_dir
    decrypted_dir = auto_detect_decrypted_dir()
    if decrypted_dir:
        messages.append(f"✓ 检测到已解密目录：{decrypted_dir}")
    else:
        messages.append("未找到已解密目录，尝试自动解密...")
        # 2. 尝试自动解密
        result = try_auto_decrypt()
        if result["success"]:
            decrypted_dir = result["decrypted_dir"]
            messages.append(f"✓ 自动解密成功：{result['message']}")
        else:
            messages.append(f"✗ 自动解密失败：{result['message']}")
            needs_manual = result["message"]

    # 3. 检测微信数据目录
    wechat_data_dir = auto_detect_wechat_data_dir()
    if wechat_data_dir:
        messages.append(f"✓ 检测到微信数据目录：{wechat_data_dir}")
    else:
        messages.append("未检测到微信数据目录（可能未安装微信或未登录）")

    # 4. 检测 self_wxid
    self_wxid = ""
    if wechat_data_dir:
        self_wxid = auto_detect_self_wxid(
            wechat_data_dir=wechat_data_dir,
            decrypted_dir=decrypted_dir or "",
        ) or ""
    if not self_wxid and decrypted_dir:
        self_wxid = auto_detect_self_wxid(decrypted_dir=decrypted_dir) or ""
    if self_wxid:
        messages.append(f"✓ 检测到本人 wxid：{self_wxid}")
    else:
        messages.append("未检测到本人 wxid（可从会话中推断，或稍后手动填写）")

    # 5. 检测 whisper
    whisper = auto_detect_whisper()
    if whisper["binary_path"]:
        messages.append(f"✓ 检测到 whisper.cpp：{whisper['binary_path']}")
        if whisper["model_path"]:
            messages.append(f"✓ 检测到 whisper 模型：{whisper['model_path']}")
        else:
            messages.append("未找到 whisper 模型（可手动下载 ggml-large-v3.bin）")
    else:
        messages.append("未检测到 whisper.cpp（可选，仅影响语音本地转录）")

    # 综合状态
    if decrypted_dir and self_wxid:
        status = "ok"
    elif decrypted_dir:
        status = "partial"
    else:
        status = "failed"

    return {
        "decrypted_dir": decrypted_dir or "",
        "wechat_base_dir": wechat_data_dir or "",
        "self_wxid": self_wxid,
        "whisper": whisper,
        "auto_setup_status": status,
        "messages": messages,
        "needs_manual_action": needs_manual,
    }
