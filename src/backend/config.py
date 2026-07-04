"""应用配置。

负责：
- 数据目录定位（开发态用项目目录，打包后用用户目录）
- 设置项读写
- 单例 Repository / TodoManager / Responder 的依赖注入
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from .storage.db import Database
from .storage.repository import Repository


def get_app_data_dir() -> Path:
    """获取应用数据目录。

    优先级：
    1. 环境变量 WTA_DATA_DIR
    2. 打包后：~/Library/Application Support/WeChatTradeAssistant (macOS)
                %APPDATA%/WeChatTradeAssistant (Windows)
                ~/.local/share/WeChatTradeAssistant (Linux)
    3. 开发态：项目根/data
    """
    env_dir = os.environ.get("WTA_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    if getattr(sys, "frozen", False):  # PyInstaller / Electron 打包
        if sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "WeChatTradeAssistant"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home())) / "WeChatTradeAssistant"
        else:
            base = Path.home() / ".local" / "share" / "WeChatTradeAssistant"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # 开发态
    here = Path(__file__).resolve().parents[2]  # src/backend/ → 上溯 2 到项目根
    dev_data = here / "data"
    dev_data.mkdir(parents=True, exist_ok=True)
    return dev_data


def get_models_dir() -> Path:
    """获取模型目录。"""
    env = os.environ.get("WTA_MODELS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parents[2]
    return here / "models"


def get_bin_dir() -> Path:
    """获取随应用打包的二进制目录（whisper-cli、silk_decoder）。"""
    env = os.environ.get("WTA_BIN_DIR")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parents[2]
    return here / "bin"


# ----------------------------------------------------------------------------
# 单例服务
# ----------------------------------------------------------------------------
_db: Optional[Database] = None
_repo: Optional[Repository] = None


def get_db() -> Database:
    global _db
    if _db is None:
        data_dir = get_app_data_dir()
        db_path = data_dir / "local.db"
        # 可选密码（从环境变量读，避免硬编码）
        password = os.environ.get("WTA_DB_PASSWORD") or None
        _db = Database(db_path=db_path, password=password)
        _db.init_schema()
    return _db


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository(get_db())
    return _repo


def reset_services() -> None:
    """重置单例（测试用）。"""
    global _db, _repo
    if _db is not None:
        _db.close_all()
    _db = None
    _repo = None
