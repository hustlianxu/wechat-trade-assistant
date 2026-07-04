r"""微信版本自适应适配器。

参考 PyWxDump 4.0 的自适应特征识别算法：
- 自动匹配不同微信版本的密钥派生逻辑
- 覆盖微信 3.6 ~ 4.0 全版本
- 处理 3.9.6.33 前后的密钥计算方式差异（0x1C 偏移量）

不同版本的核心差异：
1. 数据库位置：
   - Windows 3.x: %USERPROFILE%\Documents\WeChat Files\<wxid>\Msg\
   - Windows 4.0: %APPDATA%\Tencent\xwechat_files\<wxid>\
   - macOS: ~/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat/...
2. 密钥长度：3.x=32字节 AES-256，4.0 同样
3. SQLCipher 兼容版本：3.x 用 SQLCipher 3，4.0 用 SQLCipher 4
4. 内存偏移：3.9.6.33 前后偏移量不同（0x1C 差异）
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class Platform(str, Enum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


class WeChatGeneration(str, Enum):
    """微信大版本代际。"""

    GEN_3 = "3.x"  # 微信 3.x（经典版）
    GEN_4 = "4.x"  # 微信 4.0（新架构）
    WECOM = "wecom"  # 企业微信
    UNKNOWN = "unknown"


@dataclass
class WeChatVersionInfo:
    """微信版本信息。"""

    raw_version: str  # 原始版本字符串，如 "4.0.0.31"
    major: int
    minor: int
    patch: int
    build: int
    generation: WeChatGeneration
    platform: Platform
    sqlcipher_compatibility: int  # 3 or 4
    # 密钥提取的内存偏移修正（PyWxDump 算法）
    key_offset_adj: int = 0  # 3.9.6.33 之前为 0x1C，之后为 0

    @property
    def is_supported(self) -> bool:
        return self.generation != WeChatGeneration.UNKNOWN

    @property
    def display_name(self) -> str:
        gen_label = {
            WeChatGeneration.GEN_3: "微信 3.x",
            WeChatGeneration.GEN_4: "微信 4.0",
            WeChatGeneration.WECOM: "企业微信",
            WeChatGeneration.UNKNOWN: "未知版本",
        }.get(self.generation, "未知版本")
        return f"{gen_label} {self.raw_version} ({self.platform.value})"


# ----------------------------------------------------------------------------
# 版本号解析
# ----------------------------------------------------------------------------
_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)\.(\d+)")


def parse_version(raw: str) -> Optional[WeChatVersionInfo]:
    """解析版本字符串。

    支持形如 "4.0.0.31"、"3.9.6.33"、"4.0.1.30 (43021)" 等格式。
    """
    if not raw:
        return None
    m = _VERSION_PATTERN.search(raw)
    if not m:
        return None
    major, minor, patch, build = (int(x) for x in m.groups())
    plat = _detect_platform()

    # 代际判定
    if major == 4:
        generation = WeChatGeneration.GEN_4
        sqlcipher = 4
    elif major == 3:
        generation = WeChatGeneration.GEN_3
        sqlcipher = 3 if (major, minor, patch) < (3, 9, 6) else 4
    else:
        generation = WeChatGeneration.UNKNOWN
        sqlcipher = 4

    # 密钥偏移修正：3.9.6.33 之前偏移 0x1C (28)
    offset_adj = 0
    if generation == WeChatGeneration.GEN_3 and (major, minor, patch, build) < (3, 9, 6, 33):
        offset_adj = 0x1C

    return WeChatVersionInfo(
        raw_version=f"{major}.{minor}.{patch}.{build}",
        major=major,
        minor=minor,
        patch=patch,
        build=build,
        generation=generation,
        platform=plat,
        sqlcipher_compatibility=sqlcipher,
        key_offset_adj=offset_adj,
    )


def _detect_platform() -> Platform:
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return Platform.WINDOWS
    if sys_name == "darwin":
        return Platform.MACOS
    if sys_name == "linux":
        return Platform.LINUX
    return Platform.UNKNOWN


# ----------------------------------------------------------------------------
# 数据库路径定位
# ----------------------------------------------------------------------------
def find_wechat_data_dirs(version: WeChatVersionInfo) -> list[Path]:
    """根据版本与平台，定位微信用户数据目录候选列表。

    返回所有可能存在的候选路径，调用方根据 wxid 子目录进一步选择。
    """
    plat = version.platform
    candidates: list[Path] = []

    if plat == Platform.WINDOWS:
        if version.generation == WeChatGeneration.GEN_4:
            # 4.0: %APPDATA%\Tencent\xwechat_files\<wxid>\
            # 每个登录账号一个子目录，内含 message/ contact/ session/ 等
            appdata_roaming = Path.home() / "AppData" / "Roaming"
            appdata_local = Path.home() / "AppData" / "Local"
            for base in (
                appdata_roaming / "Tencent" / "xwechat_files",
                appdata_local / "Tencent" / "xwechat_files",
            ):
                if base.exists():
                    # xwechat_files 下每个子目录是一个账号
                    for sub in base.iterdir():
                        if sub.is_dir() and (sub / "message").exists():
                            candidates.append(sub)
                    # 也保留父目录，调用方可自行下钻
                    candidates.append(base)
        elif version.generation == WeChatGeneration.GEN_3:
            docs = Path.home() / "Documents" / "WeChat Files"
            if docs.exists():
                for sub in docs.iterdir():
                    if sub.is_dir() and (sub / "Msg").exists():
                        candidates.append(sub)
                candidates.append(docs)
    elif plat == Platform.MACOS:
        home = Path.home()
        # macOS 沙盒路径（3.x 经典版 / 4.0 共用同一 container）
        base_3x = (
            home
            / "Library"
            / "Containers"
            / "com.tencent.xinWeChat"
            / "Data"
            / "Library"
            / "Application Support"
            / "com.tencent.xinWeChat"
        )
        if base_3x.exists():
            # 2.0b4.0.9 这种子目录结构（3.x）
            for sub in base_3x.rglob("message"):
                if sub.is_dir():
                    candidates.append(sub.parent)
            # 4.0 的 message/message_0.db 结构也在这个 container 下
            # message_*.db 的父目录是 message/，再上一级才是账号根目录
            seen_4x_dirs: set[str] = set()
            for sub in base_3x.rglob("message_*.db"):
                account_dir = sub.parent.parent
                key = str(account_dir)
                if key not in seen_4x_dirs:
                    seen_4x_dirs.add(key)
                    candidates.append(account_dir)
            candidates.append(base_3x)
        # 4.0 在 Mac 上的非沙盒路径
        base_4x = home / "Library" / "Application Support" / "com.tencent.xWeChat"
        if base_4x.exists():
            for sub in base_4x.iterdir():
                if sub.is_dir() and (sub / "message").exists():
                    candidates.append(sub)
            candidates.append(base_4x)
        # 4.0 另一种 container 路径
        base_4x_alt = home / "Library" / "Containers" / "com.tencent.WeChat"
        if base_4x_alt.exists():
            seen_alt: set[str] = set()
            for sub in base_4x_alt.rglob("message_*.db"):
                account_dir = sub.parent.parent
                key = str(account_dir)
                if key not in seen_alt:
                    seen_alt.add(key)
                    candidates.append(account_dir)
            candidates.append(base_4x_alt)
        # 4.0 xwechat 命名（与 Windows 一致）
        base_xwechat = home / "Library" / "Application Support" / "xwechat_files"
        if base_xwechat.exists():
            for sub in base_xwechat.iterdir():
                if sub.is_dir() and (sub / "message").exists():
                    candidates.append(sub)
            candidates.append(base_xwechat)
    elif plat == Platform.LINUX:
        candidates.append(Path.home() / ".config" / "WeChat")

    # 去重并过滤存在的
    seen = set()
    result = []
    for p in candidates:
        key = str(p.resolve())
        if key not in seen and p.exists():
            seen.add(key)
            result.append(p)
    return result


def find_msg_db(version: WeChatVersionInfo, data_dir: Path) -> Optional[Path]:
    """在用户数据目录下找消息数据库主文件。

    微信 3.x: Msg/Multi/MSG0.db ~ MSGn.db + Misc.db
    微信 4.0: message/message_0.db ~ message_n.db
    """
    if version.generation == WeChatGeneration.GEN_3:
        msg_dir = data_dir / "Msg" / "Multi"
        if msg_dir.exists():
            for i in range(10):
                p = msg_dir / f"MSG{i}.db"
                if p.exists():
                    return p
        misc = data_dir / "Msg" / "Misc.db"
        if misc.exists():
            return misc
    elif version.generation == WeChatGeneration.GEN_4:
        # 4.0 数据目录结构：data_dir/message/message_0.db ~ message_n.db
        msg_dir = data_dir / "message"
        if msg_dir.exists():
            matches = sorted(msg_dir.glob("message_*.db"))
            if matches:
                return matches[0]
        # 兼容直接在 data_dir 下的情况
        for pattern in ("message_*.db", "MSG*.db"):
            matches = sorted(data_dir.glob(pattern))
            if matches:
                return matches[0]
        # 兜底递归搜索
        for pattern in ("message_*.db", "MSG*.db"):
            matches = sorted(data_dir.rglob(pattern))
            if matches:
                return matches[0]
    return None


def find_all_msg_dbs(version: WeChatVersionInfo, data_dir: Path) -> list[Path]:
    """找出所有消息数据库（4.0 有多个 message_N.db）。"""
    result: list[Path] = []
    if version.generation == WeChatGeneration.GEN_4:
        msg_dir = data_dir / "message"
        if msg_dir.exists():
            result.extend(sorted(msg_dir.glob("message_*.db")))
        if not result:
            result.extend(sorted(data_dir.rglob("message_*.db")))
    elif version.generation == WeChatGeneration.GEN_3:
        msg_dir = data_dir / "Msg" / "Multi"
        if msg_dir.exists():
            result.extend(sorted(msg_dir.glob("MSG*.db")))
    # 去重
    seen = set()
    unique = []
    for p in result:
        k = str(p)
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return unique


def find_all_dbs(version: WeChatVersionInfo, data_dir: Path) -> dict[str, Path]:
    """找出数据目录下所有 .db 文件，返回 相对路径 → 绝对路径 映射。

    用于多密钥解密：用户的 JSON key 以相对路径为 key，
    本函数产出的相对路径与之对应。

    注意：同时返回原始大小写键，调用方可通过 find_db_for_key 做大小写不敏感匹配。
    """
    result: dict[str, Path] = {}
    if not data_dir.exists():
        return result
    for p in data_dir.rglob("*.db"):
        rel = str(p.relative_to(data_dir)).replace("\\", "/")
        result[rel] = p
    return result


def find_db_for_key(all_dbs: dict[str, Path], db_rel_path: str) -> Optional[Path]:
    """根据 JSON 中的相对路径查找实际数据库文件，大小写不敏感。

    微信 4.0.x 在不同平台/版本下路径大小写可能不同（如 Message/Message_0.db
    vs message/message_0.db），而 SQLCipher 密钥与路径内容无关，因此做大小写
    不敏感匹配以提高兼容性。
    """
    if not db_rel_path:
        return None
    normalized = db_rel_path.replace("\\", "/").lstrip("./")
    # 精确匹配
    if normalized in all_dbs:
        return all_dbs[normalized]
    # 大小写不敏感匹配
    lower = normalized.lower()
    for rel, abs_path in all_dbs.items():
        if rel.lower() == lower:
            return abs_path
    return None


def find_micro_msg_db(version: WeChatVersionInfo, data_dir: Path) -> Optional[Path]:
    """找联系人数据库 MicroMsg.db / contact.db。"""
    if version.generation == WeChatGeneration.GEN_3:
        p = data_dir / "Msg" / "MicroMsg.db"
        return p if p.exists() else None
    elif version.generation == WeChatGeneration.GEN_4:
        # 4.0: contact/contact.db
        contact_dir = data_dir / "contact"
        if contact_dir.exists():
            p = contact_dir / "contact.db"
            if p.exists():
                return p
        # 兼容兜底
        for pattern in ("contact.db", "contact_*.db", "MicroMsg.db"):
            matches = sorted(data_dir.rglob(pattern))
            if matches:
                return matches[0]
    return None


# ----------------------------------------------------------------------------
# 版本检测入口
# ----------------------------------------------------------------------------
def detect_installed_wechat() -> Optional[WeChatVersionInfo]:
    """检测本机安装的微信版本。

    优先从可执行文件版本信息读取；失败则从数据库目录特征推断。
    在沙箱/无微信环境返回 None。
    """
    plat = _detect_platform()
    raw: Optional[str] = None

    if plat == Platform.WINDOWS:
        # Windows: 读注册表
        # 4.0 用 xwechat 项，3.x 用 WeChat 项
        try:
            import winreg  # type: ignore

            # 候选注册表路径：4.0 优先
            reg_paths = [
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Tencent\xwechat"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\xwechat"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Tencent\WeChat"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Tencent\WeChat"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Tencent\WeChat"),
            ]
            for hive, subkey in reg_paths:
                try:
                    with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                        # 版本值名可能是 Version / version / ClientVersion
                        for val_name in ("Version", "version", "ClientVersion"):
                            try:
                                raw, _ = winreg.QueryValueEx(key, val_name)
                                if raw:
                                    raw = str(raw)
                                    break
                            except OSError:
                                continue
                        if raw:
                            break
                except OSError:
                    continue
        except ImportError:
            pass
    elif plat == Platform.MACOS:
        # macOS: 读 Info.plist
        try:
            import plistlib

            for app_path in (
                Path("/Applications/WeChat.app/Contents/Info.plist"),
                Path("/Applications/微信.app/Contents/Info.plist"),
                Path("/Applications/WeChat-beta.app/Contents/Info.plist"),
            ):
                if app_path.exists():
                    with app_path.open("rb") as f:
                        plist = plistlib.load(f)
                    raw = str(plist.get("CFBundleShortVersionString", ""))
                    if not raw:
                        # 某些版本用 CFBundleVersion
                        raw = str(plist.get("CFBundleVersion", ""))
                    if raw:
                        # macOS 版本号可能只有 2~3 段，补齐到 4 段
                        parts = raw.split(".")
                        while len(parts) < 4:
                            parts.append("0")
                        raw = ".".join(parts[:4])
                        break
        except Exception:  # noqa: BLE001
            pass

    if raw:
        return parse_version(raw)
    return None


def fallback_generation_by_data_dir(data_dir: Path) -> WeChatGeneration:
    """根据数据目录特征推断代际（版本号未知时）。"""
    if any(data_dir.rglob("xwechat*")) or any(data_dir.rglob("message_*.db")):
        return WeChatGeneration.GEN_4
    if (data_dir / "Msg").exists() or any(data_dir.rglob("MSG*.db")):
        return WeChatGeneration.GEN_3
    return WeChatGeneration.UNKNOWN
