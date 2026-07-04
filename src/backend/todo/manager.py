"""待办管理器：把 ExtractedTodo 写入数据库 + 状态管理。"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from ..storage.models import Message, Todo
from ..storage.repository import Repository
from .extractor import ExtractedTodo, extract_from_messages, to_todo


class TodoManager:
    """待办事项的统一管理入口。"""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------------
    # 自动提取
    # ------------------------------------------------------------------------
    def extract_and_save(
        self,
        messages: List[Message],
        now: Optional[datetime] = None,
        skip_existing: bool = True,
    ) -> List[Todo]:
        """从消息列表中提取待办并写入数据库。

        skip_existing=True 时，会跳过同一 message_id 已提取过的待办
        （通过 detail 去重，简单近似）。
        返回新增的 Todo 列表。
        """
        if not messages:
            return []

        candidates: List[Tuple[Message, ExtractedTodo]] = extract_from_messages(messages, now=now)
        if not candidates:
            return []

        # 查现有待办的 message_id 集合，用于去重
        existing_keys: set[tuple[int, str]] = set()
        if skip_existing:
            msg_ids = [m.id for m in messages if m.id is not None]
            if msg_ids:
                # 简化：把同一 message 已有的 todos 详情收集起来
                for m in messages:
                    if m.id is None:
                        continue
                    existing = self.repo.list_todos(contact_id=m.contact_id)
                    for t in existing:
                        if t.message_id == m.id:
                            existing_keys.add((m.id, t.detail))

        new_todos: List[Todo] = []
        for msg, ext in candidates:
            if msg.id is None:
                continue
            key = (msg.id, ext.detail)
            if skip_existing and key in existing_keys:
                continue
            todo = to_todo(msg, ext)
            todo_id = self.repo.insert_todo(todo)
            todo.id = todo_id
            new_todos.append(todo)
            existing_keys.add(key)

        return new_todos

    # ------------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------------
    def mark_status(self, todo_id: int, status: str) -> None:
        """更新待办状态。status ∈ {pending, doing, done, cancelled}。"""
        if status not in {"pending", "doing", "done", "cancelled"}:
            raise ValueError(f"非法状态：{status}")
        self.repo.update_todo_status(todo_id, status)

    def update(self, todo_id: int, fields: Dict) -> None:
        """通用更新。"""
        self.repo.update_todo(todo_id, fields)

    def delete(self, todo_id: int) -> None:
        self.repo.delete_todo(todo_id)

    def add_manual(
        self,
        title: str,
        contact_id: Optional[int] = None,
        detail: str = "",
        due_ts: Optional[int] = None,
        priority: str = "normal",
    ) -> int:
        """手动新增待办。"""
        todo = Todo(
            contact_id=contact_id,
            title=title,
            detail=detail,
            due_ts=due_ts,
            status="pending",
            source="manual",
            priority=priority,
        )
        return self.repo.insert_todo(todo)

    # ------------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------------
    def list_todos(
        self,
        status: Optional[str] = None,
        contact_id: Optional[int] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        order_by: str = "due_ts",
    ) -> List[Todo]:
        return self.repo.list_todos(
            status=status,
            contact_id=contact_id,
            start_ts=start_ts,
            end_ts=end_ts,
            order_by=order_by,
        )

    def summary(self) -> Dict[str, int]:
        return self.repo.todo_summary()
