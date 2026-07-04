"""macOS 重签名助手。

macOS 因 SIP + Hardened Runtime 机制，无法直接读取微信进程内存，
必须先对 WeChat.app 做 ad-hoc 重签名：

    sudo codesign --force --deep --sign - /Applications/WeChat.app

本模块封装该操作，并提供友好的中文错误提示。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .adapter import Platform, _detect_platform


WECHAT_APP_PATHS = [
    Path("/Applications/WeChat.app"),
    Path("/Applications/微信.app"),
]


def find_wechat_app() -> Optional[Path]:
    """找到 WeChat.app 路径。"""
    for p in WECHAT_APP_PATHS:
        if p.exists():
            return p
    return None


@dataclass
class ResignResult:
    """重签名结果。"""

    success: bool
    message: str
    output: str = ""


def is_resigned() -> bool:
    """检查 WeChat.app 是否已被 ad-hoc 重签名。"""
    if _detect_platform() != Platform.MACOS:
        return False
    app_path = find_wechat_app()
    if app_path is None:
        return False
    result = subprocess.run(
        ["codesign", "-dvv", str(app_path)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        return False
    # 重签名后通常没有 TeamIdentifier，或为 "-"
    text = result.stderr
    if "TeamIdentifier=" in text:
        after = text.split("TeamIdentifier=")[-1].split("\n")[0].strip()
        return after == "" or after == "-"
    return False


def needs_resign() -> bool:
    """判断当前是否需要重签名（macOS + 未重签名）。"""
    if _detect_platform() != Platform.MACOS:
        return False
    return find_wechat_app() is not None and not is_resigned()


def perform_resign(password: Optional[str] = None) -> ResignResult:
    """执行 ad-hoc 重签名。

    Args:
        password: sudo 密码；为空则要求用户在系统弹窗输入

    Returns:
        ResignResult
    """
    if _detect_platform() != Platform.MACOS:
        return ResignResult(False, "重签名仅支持 macOS")

    app_path = find_wechat_app()
    if app_path is None:
        return ResignResult(False, "未找到 WeChat.app，请确认微信已安装到 /Applications/")

    if shutil.which("codesign") is None:
        return ResignResult(False, "未找到 codesign 命令，请确认 Xcode Command Line Tools 已安装")

    cmd = [
        "sudo", "-S",
        "codesign", "--force", "--deep", "--sign", "-",
        str(app_path),
    ]
    try:
        if password:
            # 通过 stdin 传密码（非交互）
            result = subprocess.run(
                cmd, input=f"{password}\n", capture_output=True, text=True, timeout=120, check=False
            )
        else:
            # 走系统 sudo 弹窗（用户需手动输入）
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, check=False
            )
    except subprocess.TimeoutExpired:
        return ResignResult(False, "重签名超时，请重试")

    if result.returncode == 0:
        return ResignResult(
            True,
            "重签名成功！现在可以读取微信进程内存了。",
            output=result.stdout + result.stderr,
        )
    return ResignResult(
        False,
        f"重签名失败（exit={result.returncode}）。可能原因：sudo 密码错误 / 应用正在运行 / 磁盘空间不足。",
        output=result.stdout + result.stderr,
    )
