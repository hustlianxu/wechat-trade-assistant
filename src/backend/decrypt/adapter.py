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
            # 4.0: %APPDATA%\Tencent\xwechat_files\
            appdata = Path.home() / "AppData" / "Roaming"
            candidates.append(appdata / "Tencent" / "xwechat_files")
            # 也可能放 Local
            candidates.append(Path.home() / "AppData" / "Local" / "Tencent" / "xwechat_files")
        elif version.generation == WeChatGeneration.GEN_3:
            docs = Path.home() / "Documents" / "WeChat Files"
            candidates.append(docs)
    elif plat == Platform.MACOS:
        # macOS 沙盒路径
        base = (
            Path.home()
            / "Library"
            / "Containers"
            / "com.tencent.xinWeChat"
            / "Data"
            / "Library"
            / "Application Support"
            / "com.tencent.xinWeChat"
        )
        candidates.append(base)
        # 4.0 在 Mac 上路径可能变化
        candidates.append(
            Path.home() / "Library" / "Application Support" / "com.tencent.xWeChat"
        )
    elif plat == Platform.LINUX:
        # Linux 微信（较新， Electron 化）
        candidates.append(Path.home() / ".config" / "WeChat")

    # 过滤存在的
    return [p for p in candidates if p.exists()]


def find_msg_db(version: WeChatVersionInfo, data_dir: Path) -> Optional[Path]:
    """在用户数据目录下找消息数据库主文件。

    微信 3.x: Msg/Multi/MSG0.db ~ MSGn.db + Misc.db
    微信 4.0: message_*.db（xwechat 的新命名）
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
        # 4.0 的 db 命名
        for pattern in ("message_*.db", "MSG*.db"):
            matches = sorted(data_dir.rglob(pattern))
            if matches:
                return matches[0]
    return None


def find_micro_msg_db(version: WeChatVersionInfo, data_dir: Path) -> Optional[Path]:
    """找联系人数据库 MicroMsg.db / contact.db。"""
    if version.generation == WeChatGeneration.GEN_3:
        p = data_dir / "Msg" / "MicroMsg.db"
        return p if p.exists() else None
    elif version.generation == WeChatGeneration.GEN_4:
        for pattern in ("contact_*.db", "MicroMsg.db"):
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
        # Windows: 读注册表 HKLM\SOFTWARE\Tencent\WeChat
        try:
            import winreg  # type: ignore

            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(
                        hive, r"SOFTWARE\Tencent\WeChat", 0, winreg.KEY_READ
                    ) as key:
                        raw, _ = winreg.QueryValueEx(key, "Version")
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
            ):
                if app_path.exists():
                    with app_path.open("rb") as f:
                        plist = plistlib.load(f)
                    raw = str(plist.get("CFBundleShortVersionString", ""))
                    if raw:
                        # macOS 版本号通常只有 3 段，补 build 为 0
                        if raw.count(".") == 2:
                            raw = raw + ".0"
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
