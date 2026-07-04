"""FastAPI 应用入口。

启动方式：
    python -m backend.main                # 开发态默认 127.0.0.1:8765
    WTA_PORT=9000 python -m backend.main

打包态由 Electron 主进程 spawn 此模块作为子进程，
通过 stdout 上的 `READY:<port>` 标记通知前端就绪。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import get_app_data_dir, get_repo

logger = logging.getLogger("backend.main")

# 默认监听端口（仅本机回环，不对外暴露）
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def create_app() -> FastAPI:
    """构造 FastAPI 应用实例。"""
    app = FastAPI(
        title="WeChat Trade Assistant",
        description="南美外贸微信智能助手后端 API",
        version="0.1.0",
        # 仅本机调用，关闭文档对外暴露并非必须，但保留 docs 便于开发调试
        docs_url="/docs",
        redoc_url=None,
    )

    # CORS：允许 Electron 前端（file:// 或 http://localhost）调用
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 仅本机进程，开放即可
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册所有业务路由
    app.include_router(api_router)

    # 静态资源：图片缩略图、解密后的语音文件等
    # 通过 /files/<relative_path> 访问
    data_dir = get_app_data_dir()
    assets_dir = data_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/files",
        StaticFiles(directory=str(assets_dir)),
        name="assets",
    )

    @app.on_event("startup")
    def _on_startup() -> None:
        """应用启动时初始化数据库并按需启动实时监听。"""
        try:
            # get_repo() 内部会调用 get_db()，后者已负责建表
            get_repo()
            logger.info("数据库初始化完成：%s", get_app_data_dir() / "local.db")
        except Exception as e:  # noqa: BLE001
            logger.exception("数据库初始化失败：%s", e)

        # 若用户已开启实时解析，则启动轮询监听器
        try:
            _maybe_start_realtime_listener()
        except Exception as e:  # noqa: BLE001
            logger.warning("实时监听器启动失败（可忽略）：%s", e)

        # 通知 Electron 主进程：后端已就绪
        port = os.environ.get("WTA_PORT", str(DEFAULT_PORT))
        sys.stdout.write(f"READY:{port}\n")
        sys.stdout.flush()

    @app.on_event("shutdown")
    def _on_shutdown() -> None:
        _stop_realtime_listener()

    return app


# ----------------------------------------------------------------------------
# 实时监听器（SSE / 轮询）单例
# ----------------------------------------------------------------------------
_realtime_listener: Optional[object] = None
_realtime_lock = threading.Lock()


def _maybe_start_realtime_listener() -> None:
    """若设置中 realtime_listen=1 且能检测到微信，则启动轮询监听。"""
    global _realtime_listener
    repo = get_repo()
    enabled = repo.get_all_settings().get("realtime_listen", "0") == "1"
    if not enabled:
        return

    try:
        from .decrypt import PollingListener, SSEConfig, detect_installed_wechat

        version_info = detect_installed_wechat()
        if version_info is None:
            logger.info("未检测到微信，跳过实时监听")
            return

        # SSEConfig 默认值，可后续做更精细配置
        cfg = SSEConfig(interval_seconds=15)
        listener = PollingListener(
            version_info=version_info,
            config=cfg,
            on_new_messages=_on_new_messages_callback,
        )
        listener.start()
        with _realtime_lock:
            _realtime_listener = listener
        logger.info("实时监听器已启动，间隔 %ss", cfg.interval_seconds)
    except Exception as e:  # noqa: BLE001
        logger.warning("实时监听器初始化失败：%s", e)


def _stop_realtime_listener() -> None:
    global _realtime_listener
    with _realtime_lock:
        if _realtime_listener is not None:
            try:
                _realtime_listener.stop()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
            _realtime_listener = None


def _on_new_messages_callback(messages) -> None:
    """收到新消息时的回调：写入本地库并触发意图识别 / 待办提取。"""
    try:
        repo = get_repo()
        from .decrypt import to_message_model
        from .intent import classify as classify_intent
        from .todo import TodoManager

        # 先 upsert 联系人（监听器返回的 messages 已含 contact 信息）
        msgs_to_insert = []
        for parsed, contact in messages:
            if contact is not None:
                cid = repo.upsert_contact(contact)
            else:
                cid = repo.get_contact_id_by_wxid(parsed.talker_wxid)
            if cid is None:
                continue
            m = to_message_model(parsed, cid)
            # 即时跑意图识别（仅文字）
            if m.content and m.msg_type == "text":
                intent, conf = classify_intent(m.content)
                m.intent = intent
                m.confidence = conf
            msgs_to_insert.append(m)
        if msgs_to_insert:
            repo.insert_messages_bulk(msgs_to_insert)
            # 触发待办提取
            TodoManager(repo).extract_and_save(msgs_to_insert)
            logger.info("实时导入 %d 条新消息", len(msgs_to_insert))
    except Exception as e:  # noqa: BLE001
        logger.exception("实时消息处理失败：%s", e)


# ----------------------------------------------------------------------------
# 启动入口
# ----------------------------------------------------------------------------
def run(host: str = DEFAULT_HOST, port: int | None = None) -> None:
    """启动 uvicorn 服务。"""
    import uvicorn

    if port is None:
        port = int(os.environ.get("WTA_PORT", DEFAULT_PORT))
    # 写入环境变量供 startup 事件读取
    os.environ["WTA_PORT"] = str(port)

    app = create_app()
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("WTA_LOG_LEVEL", "info"),
        # 仅本机进程，关闭访问日志以减少 stdout 噪音
        access_log=os.environ.get("WTA_ACCESS_LOG", "0") == "1",
    )


# 全局 app 实例（供 uvicorn backend.main:app 直接启动）
app = create_app()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("WTA_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run()
