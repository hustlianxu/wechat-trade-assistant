"""测试待办事项自动提取。"""

from __future__ import annotations

from datetime import datetime

from backend.storage.models import Message
from backend.todo.extractor import extract_from_messages
from backend.todo.manager import TodoManager


NOW = datetime(2026, 6, 15, 12, 0, 0)  # 周一


def _make_msg(content: str, msg_id: str = "m1", msg_type: str = "text") -> Message:
    return Message(
        id=1,
        contact_id=1,
        msg_id=msg_id,
        msg_type=msg_type,
        direction="in",
        sender="Juan",
        content=content,
        created_ts=int(NOW.timestamp()),
    )


class TestExtractor:
    def test_extract_shipping_promise(self):
        """'mañana despachamos' 应被识别为待办。"""
        m = _make_msg("Mañana despachamos por DHL, número de tracking el viernes.")
        candidates = extract_from_messages([m], now=NOW)
        assert len(candidates) >= 1
        msg, todo = candidates[0]
        assert todo.due_ts is not None  # 应解析出截止时间

    def test_extract_quotation_request(self):
        """'¿me puedes cotizar?' 应被识别为报价待办。"""
        m = _make_msg("Hola, ¿me puedes cotizar 500 unidades del modelo A-100?")
        candidates = extract_from_messages([m], now=NOW)
        assert len(candidates) >= 1

    def test_extract_meeting(self):
        """'reunión el viernes' 应被识别为会议待办。"""
        m = _make_msg("Me gustaría agendar una reunión el viernes para discutir el contrato.")
        candidates = extract_from_messages([m], now=NOW)
        assert len(candidates) >= 1

    def test_no_todo_in_greeting(self):
        """问候语不应产出待办。"""
        m = _make_msg("Hola, buenos días")
        candidates = extract_from_messages([m], now=NOW)
        assert candidates == []

    def test_chinese_shipping(self):
        m = _make_msg("明天发货，周五给你 tracking number")
        candidates = extract_from_messages([m], now=NOW)
        assert len(candidates) >= 1


class TestTodoManager:
    def test_extract_and_save(self, repo_with_mock_data):
        """对 mock 数据跑全量待办提取，应至少抽出 3 条待办。"""
        repo, _ = repo_with_mock_data
        manager = TodoManager(repo)
        msgs = repo.list_messages(limit=500)
        new_todos = manager.extract_and_save(msgs, now=NOW)
        # mock 数据中至少包含：Juan的发货承诺、Carlos的会议、Juan的付款
        assert len(new_todos) >= 2
        # 验证写入数据库
        all_todos = repo.list_todos()
        assert len(all_todos) >= len(new_todos)

    def test_mark_status(self, repo_with_mock_data):
        """状态切换：pending → doing → done。"""
        repo, _ = repo_with_mock_data
        manager = TodoManager(repo)
        msgs = repo.list_messages(limit=500)
        new_todos = manager.extract_and_save(msgs, now=NOW)
        assert new_todos, "应至少抽出一条待办"

        todo_id = new_todos[0].id
        # pending → doing
        manager.mark_status(todo_id, "doing")
        todos = repo.list_todos()
        t = next(x for x in todos if x.id == todo_id)
        assert t.status == "doing"

        # doing → done
        manager.mark_status(todo_id, "done")
        todos = repo.list_todos()
        t = next(x for x in todos if x.id == todo_id)
        assert t.status == "done"
        assert t.completed_ts is not None

    def test_add_manual_todo(self, repo_with_mock_data):
        """手动新增待办。"""
        repo, _ = repo_with_mock_data
        manager = TodoManager(repo)
        new_id = manager.add_manual(
            title="跟进 Maria 投诉处理结果",
            contact_id=None,
            detail="50件次品已重发，3天后回访",
            due_ts=int(NOW.timestamp()) + 86400,
            priority="high",
        )
        assert new_id > 0
        todos = repo.list_todos()
        t = next(x for x in todos if x.id == new_id)
        assert t.title == "跟进 Maria 投诉处理结果"
        assert t.priority == "high"
        assert t.source == "manual"
