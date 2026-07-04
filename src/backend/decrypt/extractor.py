"""微信密钥提取器。

三种来源：
1. memory：从微信进程内存扫描密钥（Windows 优先方案，需要管理员权限）
2. registry：从 Windows 注册表读取（仅 4.0 部分版本）
3. manual：用户手动粘贴密钥（兜底，UI 提供 hex 输入框）

macOS 因 SIP + Hardened Runtime，需要先对 WeChat.app 做 ad-hoc 重签名，
才能用 lldb/vmmap 读取进程内存。

本模块对 wechat-decrypt 的密钥提取能力做薄封装，
在沙箱/无微信环境会优雅返回 None 并给出错误提示。
"""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .adapter import Platform, WeChatGeneration, WeChatVersionInfo, _detect_platform

# ctypes.wintypes 仅 Windows 可用，且非必需（仅 _native_scan_memory_windows 用到）。
# 在非 Windows 平台做条件导入，避免在某些精简 Python 环境触发 ImportError。
try:
    import ctypes  # noqa: F401
    if platform.system().lower() == "windows":
        import ctypes.wintypes  # noqa: F401
except ImportError:
    pass


@dataclass
class ExtractedKey:
    """提取到的密钥。"""

    key_hex: str  # 32 字节密钥的 hex 字符串（64 字符）
    source: str   # memory / registry / manual
    pid: Optional[int] = None  # 微信进程 PID（memory 来源时填）

    @property
    def key_bytes(self) -> bytes:
        return bytes.fromhex(self.key_hex)


class KeyExtractionError(Exception):
    """密钥提取失败。"""


# ----------------------------------------------------------------------------
# memory 提取（Windows）
# ----------------------------------------------------------------------------
def extract_from_memory_windows(version: WeChatVersionInfo, pid: Optional[int] = None) -> ExtractedKey:
    """从微信进程内存中提取密钥。

    算法参考 PyWxDump：
    1. 找到 WeChat.exe 进程
    2. 用 ReadProcessMemory 扫描其可读内存段
    3. 在内存中找符合 SQLCipher 密钥特征的 32 字节序列
       （通常密钥前 8 字节是固定 magic）
    4. 加上 version.key_offset_adj 偏移修正

    需要：管理员权限 + pysqlcipher3（验证用）
    """
    if _detect_platform() != Platform.WINDOWS:
        raise KeyExtractionError("memory 提取仅支持 Windows")

    pid = pid or _find_wechat_pid_windows()
    if pid is None:
        raise KeyExtractionError("未找到运行中的微信进程，请先启动微信并登录")

    # 调用 ReadProcessMemory 扫描内存
    try:
        key = _scan_process_memory_for_key(pid, version)
    except PermissionError as e:
        raise KeyExtractionError(
            "内存读取被拒绝。请以管理员身份运行本应用后重试。"
        ) from e
    if key is None:
        raise KeyExtractionError(
            "在微信进程内存中未找到密钥。可能微信版本不兼容或微信未登录。"
        )
    return ExtractedKey(key_hex=key, source="memory", pid=pid)


def _find_wechat_pid_windows() -> Optional[int]:
    """找到 WeChat.exe / wechat.exe 主进程 PID。"""
    try:
        import psutil  # type: ignore
    except ImportError:
        # 回退 tasklist
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WeChat.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        # "WeChat.exe","1234","Console","1","50,000 K"
        first_line = result.stdout.strip().splitlines()[0]
        parts = first_line.split('","')
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None

    for proc in psutil.process_iter(["pid", "name"]):
        if proc.info["name"] and proc.info["name"].lower() in ("wechat.exe", "wechat.dll"):
            return proc.info["pid"]
    return None


def _scan_process_memory_for_key(pid: int, version: WeChatVersionInfo) -> Optional[str]:
    """扫描进程内存，找 32 字节 SQLCipher 密钥。

    实现说明：完整实现需要遍历 VirtualQueryEx + ReadProcessMemory，
    用 win32api 直接调用较冗长。这里给出关键骨架，
    生产环境推荐直接复用 wechat-decrypt 项目的 wx_info.py。
    """
    # 占位实现：在沙箱/无 win32api 环境直接返回 None
    # 真实环境会调用 wechat-decrypt 的 wx_info.dump_key(pid, version)
    try:
        # 尝试调用 wechat-decrypt 库（如果用户已安装）
        from wcd import wx_info  # type: ignore  # wechat-decrypt 的密钥模块

        key = wx_info.dump_key(pid, version.raw_version, offset_adj=version.key_offset_adj)
        if isinstance(key, bytes):
            return key.hex()
        if isinstance(key, str):
            return key
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[decrypt] wechat-decrypt 提取失败：{e}")

    # 原生 ReadProcessMemory 兜底（仅 Windows）
    if _detect_platform() == Platform.WINDOWS:
        try:
            return _native_scan_memory_windows(pid, version)
        except Exception as e:  # noqa: BLE001
            print(f"[decrypt] 原生内存扫描失败：{e}")

    return None


def _native_scan_memory_windows(pid: int, version: WeChatVersionInfo) -> Optional[str]:
    """用 ctypes 调 Windows API 扫描内存。

    实际生产代码很长（几百行），这里只放最小可工作骨架，
    优先建议直接复用 wechat-decrypt 的实现。
    """
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ = 0x0010
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise PermissionError(f"OpenProcess 失败，可能需要管理员权限 (err={kernel32.GetLastError()})")
    try:
        # 完整扫描逻辑略，需遍历 MEM_COMMIT 区块
        # 参考 wechat-decrypt/decrypt/wx_info.py 的 scan_region
        return None  # 占位：真实实现需复用 wechat-decrypt
    finally:
        kernel32.CloseHandle(h)


# ----------------------------------------------------------------------------
# memory 提取（macOS）
# ----------------------------------------------------------------------------
def extract_from_memory_macos(version: WeChatVersionInfo) -> ExtractedKey:
    """从 macOS 微信进程内存提取密钥。

    前置条件：必须已对 WeChat.app 做 ad-hoc 重签名（见 macos_helper.py）。
    算法：
    1. 找到 WeChat 进程 PID
    2. 用 lldb attach 或 vmmap 扫描内存
    3. 找密钥特征字节
    """
    if _detect_platform() != Platform.MACOS:
        raise KeyExtractionError("macOS memory 提取仅在 macOS 可用")

    # 检查是否已重签名
    if not _is_wechat_resigned():
        raise KeyExtractionError(
            "微信尚未重签名，无法读取进程内存。"
            "请在设置页执行『一键重签名』操作后重试。"
        )

    pid = _find_wechat_pid_macos()
    if pid is None:
        raise KeyExtractionError("未找到运行中的微信进程，请先启动微信并登录")

    # 使用 lldb 提取（参考 wechat-mcp-macos 实现）
    try:
        key = _lldb_extract_key(pid)
    except Exception as e:  # noqa: BLE001
        raise KeyExtractionError(f"lldb 提取失败：{e}") from e
    if key is None:
        raise KeyExtractionError("lldb 未在内存中找到密钥")
    return ExtractedKey(key_hex=key, source="memory", pid=pid)


def _find_wechat_pid_macos() -> Optional[int]:
    result = subprocess.run(
        ["pgrep", "-x", "WeChat"], capture_output=True, text=True, timeout=5, check=False
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return int(result.stdout.strip().splitlines()[0])
        except ValueError:
            return None
    return None


def _is_wechat_resigned() -> bool:
    """检查 WeChat.app 是否已被 ad-hoc 重签名。"""
    result = subprocess.run(
        ["codesign", "-dv", "/Applications/WeChat.app"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    # 重签名后 TeamIdentifier 通常为空或为 "-"
    return result.returncode == 0 and "TeamIdentifier" in result.stderr and "not set" in result.stderr.lower() or "-" in result.stderr.split("TeamIdentifier=")[-1].split("\n")[0]


def _lldb_extract_key(pid: int) -> Optional[str]:
    """用 lldb 附加进程、扫描内存找密钥。

    实际实现参考 wechat-mcp-macos 的 lldb 脚本，较长。
    此处为接口占位。
    """
    # 占位：真实环境应调用 wechat-decrypt.macos.lldb_scan_key(pid)
    try:
        from wcd.macos import lldb_scan_key  # type: ignore

        key = lldb_scan_key(pid)
        return key.hex() if isinstance(key, bytes) else key
    except ImportError:
        return None


# ----------------------------------------------------------------------------
# 注册表（仅 Windows 4.0 部分版本可用）
# ----------------------------------------------------------------------------
def extract_from_registry_windows(version: WeChatVersionInfo) -> ExtractedKey:
    """从注册表读取密钥（部分 4.0 版本支持）。"""
    if _detect_platform() != Platform.WINDOWS:
        raise KeyExtractionError("注册表提取仅支持 Windows")
    if version.generation != WeChatGeneration.GEN_4:
        raise KeyExtractionError("注册表提取仅支持微信 4.0")

    try:
        import winreg  # type: ignore
    except ImportError:
        raise KeyExtractionError("winreg 不可用")

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Tencent\xwechat",
            0,
            winreg.KEY_READ,
        ) as key:
            data, _ = winreg.QueryValueEx(key, "Key")
            # data 可能是 bytes 或 hex 字符串
            if isinstance(data, bytes):
                if len(data) == 32:
                    return ExtractedKey(key_hex=data.hex(), source="registry")
            if isinstance(data, str):
                cleaned = data.replace("-", "").replace(" ", "")
                if len(cleaned) == 64:
                    return ExtractedKey(key_hex=cleaned, source="registry")
    except OSError as e:
        raise KeyExtractionError(f"注册表无密钥项：{e}") from e

    raise KeyExtractionError("注册表中未找到密钥（当前版本可能不支持）")


# ----------------------------------------------------------------------------
# 手动输入
# ----------------------------------------------------------------------------
HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_manual_key(key_hex: str) -> bool:
    """校验用户手动输入的密钥格式。"""
    cleaned = key_hex.strip().replace("-", "").replace(" ", "").lower()
    return bool(HEX_PATTERN.match(cleaned))


def make_manual_key(key_hex: str) -> ExtractedKey:
    """构造手动输入的 ExtractedKey。"""
    cleaned = key_hex.strip().replace("-", "").replace(" ", "").lower()
    if not validate_manual_key(cleaned):
        raise KeyExtractionError("密钥格式错误，应为 64 位 hex 字符串")
    return ExtractedKey(key_hex=cleaned, source="manual")


# ----------------------------------------------------------------------------
# 多数据库密钥（微信 4.0.x）
# ----------------------------------------------------------------------------
@dataclass
class MultiKeyEntry:
    """单个数据库的密钥条目。

    微信 4.0.x 对每个 .db 文件使用独立的 SQLCipher 密钥，
    因此需要按 db 相对路径映射到各自的 enc_key。
    """

    db_rel_path: str  # 相对数据目录的路径，如 "message/message_0.db"
    key_hex: str      # 64 位 hex 密钥

    @property
    def key_bytes(self) -> bytes:
        return bytes.fromhex(self.key_hex)


def parse_multi_keys_json(raw: str) -> Dict[str, MultiKeyEntry]:
    """解析用户提供的多密钥 JSON。

    输入格式（来自 PyWxDump / wechat-decrypt 等工具导出）：
        {
          "message/message_0.db": {"enc_key": "4fb2f098..."},
          "contact/contact.db": {"enc_key": "64989d4f..."},
          ...
        }

    Returns:
        dict[db_rel_path -> MultiKeyEntry]
    """
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise KeyExtractionError(f"多密钥 JSON 格式错误：{e}") from e

    if not isinstance(data, dict):
        raise KeyExtractionError("多密钥 JSON 顶层应为对象")

    result: Dict[str, MultiKeyEntry] = {}
    for db_path, entry in data.items():
        if not isinstance(entry, dict):
            raise KeyExtractionError(f"密钥条目 {db_path} 不是对象")
        key_hex = entry.get("enc_key") or entry.get("key") or entry.get("key_hex")
        if not key_hex:
            raise KeyExtractionError(f"密钥条目 {db_path} 缺少 enc_key 字段")
        cleaned = str(key_hex).strip().replace("-", "").replace(" ", "").lower()
        if not HEX_PATTERN.match(cleaned):
            raise KeyExtractionError(f"密钥 {db_path} 格式错误，应为 64 位 hex")
        # 统一路径分隔符为正斜杠
        normalized = db_path.replace("\\", "/").lstrip("./")
        result[normalized] = MultiKeyEntry(db_rel_path=normalized, key_hex=cleaned)
    return result


def validate_multi_keys_json(raw: str) -> bool:
    """校验多密钥 JSON 格式是否合法。"""
    try:
        parse_multi_keys_json(raw)
        return True
    except KeyExtractionError:
        return False


# ----------------------------------------------------------------------------
# 统一入口
# ----------------------------------------------------------------------------
def extract_key(
    version: WeChatVersionInfo,
    source: str = "auto",
    pid: Optional[int] = None,
    manual_key: Optional[str] = None,
) -> ExtractedKey:
    """统一密钥提取入口。

    Args:
        version: 微信版本信息
        source: memory / registry / manual / auto
        pid: 微信进程 PID（memory 时可选）
        manual_key: 手动密钥 hex（manual 时必填）

    source=auto 时按 platform 与 generation 选最优策略。
    """
    if source == "manual":
        if not manual_key:
            raise KeyExtractionError("manual 来源需要 manual_key 参数")
        return make_manual_key(manual_key)

    if source == "auto":
        plat = version.platform
        if plat == Platform.WINDOWS:
            # 先 registry，失败再 memory
            try:
                return extract_from_registry_windows(version)
            except KeyExtractionError:
                return extract_from_memory_windows(version, pid=pid)
        elif plat == Platform.MACOS:
            return extract_from_memory_macos(version)
        else:
            raise KeyExtractionError(f"当前平台 {plat.value} 不支持自动提取")

    if source == "memory":
        if version.platform == Platform.WINDOWS:
            return extract_from_memory_windows(version, pid=pid)
        elif version.platform == Platform.MACOS:
            return extract_from_memory_macos(version)
        else:
            raise KeyExtractionError(f"当前平台不支持 memory 提取")

    if source == "registry":
        return extract_from_registry_windows(version)

    raise KeyExtractionError(f"未知来源：{source}")
