"""测试 storage 模块：Repository CRUD + FTS 检索。"""

from __future__ import annotations

from backend.storage.models import Contact, Message, QueryFilter


class TestContactCRUD:
    def test_upsert_and_list(self, repo):
        c = Contact(wxid="wx_001", nickname="测试用户", remark="备注A", region="Chile")
        cid = repo.upsert_contact(c)
        assert cid > 0

        contacts = repo.list_contacts()
        assert len(contacts) == 1
        assert contacts[0].nickname == "测试用户"

    def test_upsert_idempotent(self, repo):
        """同 wxid 重复 upsert 不应产生重复行。"""
        c1 = Contact(wxid="wx_001", nickname="A")
        c2 = Contact(wxid="wx_001", nickname="A_updated")
        id1 = repo.upsert_contact(c1)
        id2 = repo.upsert_contact(c2)
        assert id1 == id2
        assert len(repo.list_contacts()) == 1

    def test_get_by_wxid(self, repo):
        c = Contact(wxid="wx_002", nickname="Juan")
        cid = repo.upsert_contact(c)
        assert repo.get_contact_id_by_wxid("wx_002") == cid
        assert repo.get_contact_id_by_wxid("not_exist") is None

    def test_filter_by_intent(self, repo):
        # upsert 不写 last_intent（避免重新同步时覆盖计算结果）
        # 需通过 update_contact_intent 单独设置
        cid_a = repo.upsert_contact(Contact(wxid="a", nickname="A"))
        cid_b = repo.upsert_contact(Contact(wxid="b", nickname="B"))
        repo.update_contact_intent(cid_a, "quotation", ts=1000)
        repo.update_contact_intent(cid_b, "order_intent", ts=1000)

        quotes = repo.list_contacts(intent="quotation")
        assert len(quotes) == 1
        assert quotes[0].nickname == "A"


class TestMessageCRUD:
    def test_insert_and_list(self, repo):
        cid = repo.upsert_contact(Contact(wxid="wx_001", nickname="A"))
        m = Message(
            contact_id=cid, msg_id="m001", msg_type="text",
            direction="in", sender="A", content="Hola, ¿cotización?", created_ts=1000,
        )
        mid = repo.insert_message(m)
        assert mid > 0

        msgs = repo.list_messages(contact_id=cid)
        assert len(msgs) == 1
        assert msgs[0].content == "Hola, ¿cotización?"

    def test_dedup_by_msg_id(self, repo):
        cid = repo.upsert_contact(Contact(wxid="wx_001", nickname="A"))
        m1 = Message(contact_id=cid, msg_id="dup_001", content="msg1", created_ts=1)
        m2 = Message(contact_id=cid, msg_id="dup_001", content="msg2", created_ts=2)
        repo.insert_message(m1)
        repo.insert_message(m2)
        assert len(repo.list_messages(contact_id=cid)) == 1

    def test_time_range_filter(self, repo):
        cid = repo.upsert_contact(Contact(wxid="wx_001", nickname="A"))
        repo.insert_message(Message(contact_id=cid, msg_id="t1", content="old", created_ts=1000))
        repo.insert_message(Message(contact_id=cid, msg_id="t2", content="new", created_ts=2000))
        repo.insert_message(Message(contact_id=cid, msg_id="t3", content="newer", created_ts=3000))

        # 查 1500 ~ 2500 之间
        msgs = repo.list_messages(contact_id=cid, start_ts=1500, end_ts=2500)
        assert len(msgs) == 1
        assert msgs[0].content == "new"


class TestFTSSearch:
    def test_search_by_keyword(self, repo_with_mock_data):
        """FTS 全文搜索：搜索 'cotización' 应命中 Juan 的报价消息。"""
        repo, wxid_to_id = repo_with_mock_data
        juan_id = wxid_to_id["juan_perez_88"]

        qf = QueryFilter(
            contact_ids=[juan_id],
            keywords=["cotización"],
            raw_query="test",
        )
        results = repo.search_messages(qf, limit=50)
        assert len(results) >= 1
        assert any("cotiz" in m.content.lower() for m in results)

    def test_search_across_contacts(self, repo_with_mock_data):
        """跨客户搜索 'precio' 应命中多个客户。"""
        repo, _ = repo_with_mock_data
        qf = QueryFilter(keywords=["precio"], raw_query="test")
        results = repo.search_messages(qf, limit=50)
        # 至少 Juan 的 "precio con envío" 命中
        assert len(results) >= 1

    def test_search_no_match(self, repo_with_mock_data):
        repo, _ = repo_with_mock_data
        qf = QueryFilter(keywords=["不存在的关键词xyz"], raw_query="test")
        results = repo.search_messages(qf, limit=50)
        assert results == []


class TestAssistantTurn:
    def test_insert_and_list(self, repo):
        from backend.storage.models import AssistantTurn

        u = AssistantTurn(role="user", content="查 Juan 上周聊天", engine="local")
        a = AssistantTurn(role="assistant", content="未找到记录", engine="local", latency_ms=42)
        uid = repo.insert_assistant_turn(u)
        aid = repo.insert_assistant_turn(a)
        assert uid > 0 and aid > 0

        turns = repo.list_assistant_turns(limit=10)
        assert len(turns) == 2
        assert turns[0].role == "user"  # 默认按时间升序

    def test_persistence(self, repo_with_mock_data):
        repo, _ = repo_with_mock_data
        from backend.storage.models import AssistantTurn

        before = len(repo.list_assistant_turns())
        repo.insert_assistant_turn(AssistantTurn(role="user", content="测试", engine="local"))
        after = len(repo.list_assistant_turns())
        assert after == before + 1
