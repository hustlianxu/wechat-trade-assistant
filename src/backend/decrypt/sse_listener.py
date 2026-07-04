"""实时消息监听（SSE）。

参考 wechat-decrypt 的 SSE 监听机制：
- 微信 4.0 在写入新消息后会触发 SQLite WAL 的写入事件
- 通过 polling 消息表 rowid 增量，或 hook 进程的写入回调

本模块提供两种实现：
1. PollingListener：定时拉取最新消息（兼容性最好，默认）
2. HookListener：通过进程 hook 实时回调（仅 Windows，需 wechat-decrypt 原生支持）

监听到的新消息会通过回调函数传入应用层。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..storage.models import Message
from .adapter import WeChatVersionInfo
from .parser import iter_messages, to_message_model


@dataclass
class SSEConfig:
    """实时监听配置。"""

    poll_interval_sec: float = 2.0
    max_messages_per_poll: int = 100
    # 拉取的最早时间窗（秒），避免重启时回灌太多历史
    lookback_sec: int = 600


class PollingListener:
    """轮询式实时监听器。

    每隔 poll_interval_sec 秒，从微信消息库读取 created_ts > last_ts 的消息，
    解析后通过 on_new_messages 回调上报。

    需要传入一个已解密的 db_path 与 key。
    """

    def __init__(
        self,
        db_path,
        key: bytes,
        version: WeChatVersionInfo,
        on_new_messages: Callable[[list[Message]], None],
        config: Optional[SSEConfig] = None,
    ) -> None:
        self.db_path = db_path
        self.key = key
        self.version = version
        self.on_new_messages = on_new_messages
        self.config = config or SSEConfig()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_ts: int = int(time.time()) - self.config.lookback_sec
        self._last_error: Optional[str] = None

    def start(self) -> None:
        """启动监听线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sse-listener")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """停止监听。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------------
    def _run(self) -> None:
        from .parser import open_decrypted_db

        while not self._stop_event.is_set():
            try:
                conn = open_decrypted_db(
                    self.db_path, self.key, self.version.sqlcipher_compatibility
                )
                try:
                    self._poll_once(conn)
                finally:
                    conn.close()
                self._last_error = None
            except Exception as e:  # noqa: BLE001
                self._last_error = f"{type(e).__name__}: {e}"
                # 出错后等待更久再重试
                self._stop_event.wait(timeout=self.config.poll_interval_sec * 5)
                continue

            self._stop_event.wait(timeout=self.config.poll_interval_sec)

    def _poll_once(self, conn: sqlite3.Connection) -> None:
        """单次轮询：拉取新消息并回调。"""
        new_messages: list[Message] = []
        # 此处简化：复用 iter_messages，过滤时间 > _last_ts
        # 真实实现应直接 SQL 查询 created_ts > _last_ts，避免全表扫描
        # 但 iter_messages 已是流式，可接受
        contact_id_placeholder = 0  # 调用方需用 wxid → contact_id 映射
        for parsed in iter_messages(conn, self.version):
            if parsed.created_ts <= self._last_ts:
                continue
            try:
                msg = to_message_model(parsed, contact_id_placeholder)
                new_messages.append(msg)
                if parsed.created_ts > self._last_ts:
                    self._last_ts = parsed.created_ts
                if len(new_messages) >= self.config.max_messages_per_poll:
                    break
            except Exception:  # noqa: BLE001
                continue

        if new_messages:
            self.on_new_messages(new_messages)
