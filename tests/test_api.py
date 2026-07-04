"""测试 FastAPI 路由（通过 TestClient）。

不发起真实 HTTP 服务，使用 fastapi.testclient.TestClient。
"""

from __future__ import annotations

from backend.main import create_app
from backend import config as cfg


class TestHealthAndDashboard:
    def test_health(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "ts" in body

    def test_dashboard_empty(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert body["today_todo_count"] == 0
        assert body["pending_todo_count"] == 0


class TestContactsAndMessages:
    def test_list_contacts_empty(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/contacts")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["contacts"] == []

    def test_insert_and_list(self, repo, tmp_data_dir):
        """通过 repo 直接写数据，再走 API 读出。"""
        from backend.storage.models import Contact, Message
        cid = repo.upsert_contact(Contact(wxid="wx_t", nickname="TestUser"))
        repo.insert_message(Message(
            contact_id=cid, msg_id="m1", content="Hola", created_ts=1000,
        ))

        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/contacts")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["contacts"][0]["nickname"] == "TestUser"

        r2 = c.get(f"/api/contacts/{cid}/messages")
        assert r2.status_code == 200
        assert r2.json()["total"] == 1


class TestAssistantAPI:
    def test_query_empty_db(self, tmp_data_dir):
        """空库下 MCP 查询应返回 200 + 兜底回复。"""
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.post("/api/assistant/query", json={"text": "查 Juan 上周聊天", "use_cloud": False})
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "assistant"
        assert body["engine"] == "local"
        assert body["content"]  # 非空兜底文案

    def test_query_with_mock_data(self, repo_with_mock_data, tmp_data_dir):
        """有 mock 数据时查询应返回匹配的消息。"""
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.post(
            "/api/assistant/query",
            json={"text": "上周和 Juan 聊了什么", "use_cloud": False},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] == "local"
        # 应检索到 Juan 的消息
        assert len(body["messages"]) >= 1

    def test_history(self, tmp_data_dir):
        """历史对话接口应能返回之前提问的记录。"""
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        # 先问一次
        c.post("/api/assistant/query", json={"text": "测试问题", "use_cloud": False})
        # 拉历史
        r = c.get("/api/assistant/history")
        assert r.status_code == 200
        body = r.json()
        # 至少有一对 user + assistant
        assert len(body["turns"]) >= 2


class TestTodosAPI:
    def test_create_update_delete(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)

        # 新建
        r = c.post("/api/todos", json={
            "title": "跟进订单",
            "contact_id": None,
            "detail": "测试",
            "priority": "normal",
        })
        assert r.status_code == 200
        todo = r.json()
        assert todo["title"] == "跟进订单"
        todo_id = todo["id"]

        # 更新状态
        r2 = c.patch(f"/api/todos/{todo_id}", json={"status": "doing"})
        assert r2.status_code == 200

        # 列表
        r3 = c.get("/api/todos")
        assert r3.status_code == 200
        assert r3.json()["total"] == 1

        # 删除
        r4 = c.delete(f"/api/todos/{todo_id}")
        assert r4.status_code == 200
        assert c.get("/api/todos").json()["total"] == 0

    def test_summary(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/todos/summary")
        assert r.status_code == 200
        body = r.json()
        assert "by_status" in body
        assert "by_contact" in body


class TestIntentAPI:
    def test_classify(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.post("/api/intent/classify", json={"text": "¿cotización por favor?"})
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "quotation"

    def test_batch_classify(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.post("/api/intent/classify/batch", json={
            "texts": ["cotizar 100", "hacer pedido", "gracias"]
        })
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 3
        assert results[0]["intent"] == "quotation"
        assert results[1]["intent"] == "order_intent"


class TestSettingsAPI:
    def test_get_settings(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        assert "data_dir" in body
        assert "llm_api_key_set" in body

    def test_set_and_clear_llm(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        # 设置
        r = c.post("/api/settings/llm", json={
            "api_base": "https://api.deepseek.com",
            "api_key": "sk-test",
            "model": "deepseek-chat",
            "timeout": 30.0,
        })
        assert r.status_code == 200
        # 验证已保存
        s = c.get("/api/settings").json()
        assert s["llm_api_key_set"] is True
        assert s["llm_api_base"] == "https://api.deepseek.com"
        # 清除
        r2 = c.delete("/api/settings/llm")
        assert r2.status_code == 200
        s2 = c.get("/api/settings").json()
        assert s2["llm_api_key_set"] is False

    def test_realtime_toggle(self, tmp_data_dir):
        app = create_app()
        from fastapi.testclient import TestClient
        c = TestClient(app)
        r = c.post("/api/settings/realtime", json={"enabled": True})
        assert r.status_code == 200
        s = c.get("/api/settings").json()
        assert s["realtime_listen"] is True
