"""配置管理：数据目录、LLM 配置、whisper.cpp 路径等。

配置文件位于 ~/.wta_ui/config.json，首次运行自动创建。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def get_config_dir() -> Path:
    """配置目录：~/.wta_ui/"""
    d = Path.home() / ".wta_ui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_config_path() -> Path:
    return get_config_dir() / "config.json"


def load_config() -> dict:
    """加载配置，不存在则返回默认值。"""
    p = get_config_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default_config()


def save_config(cfg: dict) -> None:
    """保存配置到磁盘。"""
    p = get_config_path()
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def default_config() -> dict:
    return {
        # wechat-decrypt 解密后的数据库目录（decrypted/）
        "decrypted_dir": "",
        # 微信数据根目录（用于定位语音/图片文件，即 xwechat_files 父目录）
        "wechat_base_dir": "",
        # 本账号 wxid（从目录名提取或手动填写）
        "self_wxid": "",
        # whisper.cpp 配置
        "whisper": {
            # whisper.cpp 可执行文件路径（brew install whisper-cpp 后通常为 /opt/homebrew/bin/whisper-cpp）
            "binary_path": "",
            # 模型路径（brew 安装后通常在 /opt/homebrew/share/whisper-cpp/）
            "model_path": "",
            # 语言提示（空=自动检测，es=西班牙语，en=英语，zh=普通话）
            "language": "",
        },
        # 多 LLM 配置列表（可配置多个，通过 active 名称切换）
        "llm_providers": [],
        # 当前激活的 LLM 名称
        "active_llm": "",
    }


def update_config(updates: dict) -> dict:
    """合并更新配置并保存。"""
    cfg = load_config()
    cfg.update(updates)
    save_config(cfg)
    return cfg
