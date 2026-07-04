"""WeChat Trade Assistant 后端包。

模块组织：
- `decrypt`：基于 wechat-decrypt 的解密引擎（密钥提取、库解析、图片解密、SSE 监听）
- `storage`：本地 SQLite 存储与数据模型
- `stt`：本地语音转录（whisper.cpp 封装 + SILK 转码）
- `intent`：意图识别（Intento-v1 封装 + 规则兜底）
- `todo`：待办提取与管理
- `mcp`：自然语言查询解析、检索、回答生成
- `api`：FastAPI 路由与 Pydantic schemas
- `config`：应用配置与单例服务
"""

from __future__ import annotations

__version__ = "0.1.0"
