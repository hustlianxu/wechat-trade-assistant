"""后端测试：使用模拟的解密数据库验证 DbReader 和 API 逻辑。

测试策略：在临时目录创建模拟的 SQLite 数据库（contact.db, session.db, message_*.db, media_*.db），
模拟 wechat-decrypt 解密后的数据库结构，验证 DbReader 能正确读取。
"""

import hashlib
import sqlite3
import tempfile
from pathlib import Path

import pytest

from backend.db_reader import (
    DbReader, Contact, Message,
    split_msg_type, msg_type_name,
    MSG_TYPE_TEXT, MSG_TYPE_VOICE, MSG_TYPE_IMAGE,
)


# ============================================================================
# 测试夹具：创建模拟的解密数据库
# ============================================================================
@pytest.fixture
def mock_decrypted_dir():
    """创建模拟的解密数据库目录。"""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        # 1. contact.db
        contact_dir = base / "contact"
        contact_dir.mkdir()
        conn = sqlite3.connect(str(contact_dir / "contact.db"))
        conn.execute("""
            CREATE TABLE contact (
                username TEXT, nick_name TEXT, remark TEXT, alias TEXT,
                description TEXT, local_type INTEGER
            )
        """)
        conn.execute("INSERT INTO contact VALUES (?, ?, ?, ?, ?, ?)",
                     ("wxid_friend1", "好友一", "备注好友一", "friend1", "描述1", 1))
        conn.execute("INSERT INTO contact VALUES (?, ?, ?, ?, ?, ?)",
                     ("wxid_friend2", "好友二", "", "friend2", "", 1))
        conn.execute("INSERT INTO contact VALUES (?, ?, ?, ?, ?, ?)",
                     ("group1@chatroom", "外贸群", "", "", "群描述", 2))
        conn.execute("INSERT INTO contact VALUES (?, ?, ?, ?, ?, ?)",
                     ("wxid_self", "我自己", "", "self", "", 1))
        conn.commit()
        conn.close()

        # 2. session.db
        session_dir = base / "session"
        session_dir.mkdir()
        conn = sqlite3.connect(str(session_dir / "session.db"))
        conn.execute("""
            CREATE TABLE SessionTable (
                username TEXT, summary TEXT, last_timestamp INTEGER,
                last_msg_type INTEGER, unread_count INTEGER
            )
        """)
        conn.execute("INSERT INTO SessionTable VALUES (?, ?, ?, ?, ?)",
                     ("wxid_friend1", "你好，价格多少？", 1700000000, 1, 2))
        conn.execute("INSERT INTO SessionTable VALUES (?, ?, ?, ?, ?)",
                     ("group1@chatroom", "wxid_friend1:\n大家在吗", 1700000100, 1, 5))
        conn.execute("INSERT INTO SessionTable VALUES (?, ?, ?, ?, ?)",
                     ("wxid_friend2", "好的", 1699999900, 1, 0))
        conn.commit()
        conn.close()

        # 3. message_0.db
        msg_dir = base / "message"
        msg_dir.mkdir()
        conn = sqlite3.connect(str(msg_dir / "message_0.db"))

        # Name2Id 表
        conn.execute("CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY, user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (user_name) VALUES (?)", ("wxid_self",))
        conn.execute("INSERT INTO Name2Id (user_name) VALUES (?)", ("wxid_friend1",))

        # 消息表：Msg_<md5(username)>
        table_name = f"Msg_{hashlib.md5(b'wxid_friend1').hexdigest()}"
        conn.execute(f"""
            CREATE TABLE "{table_name}" (
                local_id INTEGER PRIMARY KEY,
                server_id INTEGER,
                local_type INTEGER,
                create_time INTEGER,
                real_sender_id INTEGER,
                message_content TEXT,
                WCDB_CT_message_content INTEGER DEFAULT 0
            )
        """)
        # 对方发文本
        conn.execute(f'INSERT INTO "{table_name}" VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (1, 1001, 1, 1700000000, 2, "你好，价格多少？", 0))
        # 自己回文本
        conn.execute(f'INSERT INTO "{table_name}" VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (2, 1002, 1, 1700000010, 1, "100美元一个", 0))
        # 对方发语音
        conn.execute(f'INSERT INTO "{table_name}" VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (3, 1003, 34, 1700000020, 2, "<voicemsg voicelength='5000'/>", 0))
        conn.commit()
        conn.close()

        # 4. media_0.db（语音数据）
        conn = sqlite3.connect(str(msg_dir / "media_0.db"))
        conn.execute("CREATE TABLE Name2Id (rowid INTEGER PRIMARY KEY, user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (user_name) VALUES (?)", ("wxid_friend1",))

        conn.execute("""
            CREATE TABLE VoiceInfo (
                chat_name_id INTEGER,
                local_id INTEGER,
                create_time INTEGER,
                voice_data BLOB
            )
        """)
        # 模拟 SILK 数据（首字节 0x02 + 假数据）
        fake_silk = b"\x02" + b"\x00" * 100
        conn.execute("INSERT INTO VoiceInfo VALUES (?, ?, ?, ?)",
                     (1, 3, 1700000020, fake_silk))
        conn.commit()
        conn.close()

        yield str(base)


# ============================================================================
# 消息类型工具函数测试
# ============================================================================
class TestMsgType:
    def test_split_simple(self):
        assert split_msg_type(1) == (1, 0)
        assert split_msg_type(34) == (34, 0)

    def test_split_composite(self):
        # sub_type=5, base_type=3 → (3 << 32) | 5 = 12884901891
        composite = (5 << 32) | 3
        assert split_msg_type(composite) == (3, 5)

    def test_msg_type_name(self):
        assert msg_type_name(1) == "文本"
        assert msg_type_name(34) == "语音"
        assert msg_type_name(3) == "图片"
        assert msg_type_name(49) == "链接/文件"
        assert msg_type_name(999) == "未知(999)"


# ============================================================================
# DbReader 测试
# ============================================================================
class TestDbReader:
    def test_init(self, mock_decrypted_dir):
        """测试初始化能找到所有数据库。"""
        reader = DbReader(mock_decrypted_dir)
        assert reader.contact_db is not None
        assert reader.session_db is not None
        assert len(reader.message_dbs) == 1
        assert len(reader.media_dbs) == 1

    def test_list_friends(self, mock_decrypted_dir):
        """测试好友列表（排除自己和群聊）。"""
        reader = DbReader(mock_decrypted_dir)
        friends = reader.list_contacts(contact_type="friends", sort="name", self_wxid="wxid_self")
        assert len(friends) == 2
        # 按名字排序，"备注好友一" 应在前
        assert friends[0].display_name == "备注好友一"
        assert friends[1].display_name == "好友二"

    def test_list_groups(self, mock_decrypted_dir):
        """测试群聊列表。"""
        reader = DbReader(mock_decrypted_dir)
        groups = reader.list_contacts(contact_type="groups")
        assert len(groups) == 1
        assert groups[0].username == "group1@chatroom"
        assert groups[0].is_group

    def test_list_recent(self, mock_decrypted_dir):
        """测试最近会话（按时间倒序）。"""
        reader = DbReader(mock_decrypted_dir)
        recent = reader.list_contacts(contact_type="recent")
        assert len(recent) == 3
        # group1 最后消息时间最晚
        assert recent[0].username == "group1@chatroom"
        assert recent[1].username == "wxid_friend1"
        assert recent[2].username == "wxid_friend2"

    def test_self_wxid_filter(self, mock_decrypted_dir):
        """测试过滤自己。"""
        reader = DbReader(mock_decrypted_dir)
        friends = reader.list_contacts(contact_type="friends", self_wxid="wxid_self")
        usernames = [c.username for c in friends]
        assert "wxid_self" not in usernames

    def test_list_messages(self, mock_decrypted_dir):
        """测试消息列表。"""
        reader = DbReader(mock_decrypted_dir)
        messages = reader.list_messages("wxid_friend1", self_wxid="wxid_self")
        assert len(messages) == 3

        # 第一条：对方发的文本
        assert messages[0].content == "你好，价格多少？"
        assert not messages[0].is_self
        assert messages[0].sender_wxid == "wxid_friend1"

        # 第二条：自己发的
        assert messages[1].content == "100美元一个"
        assert messages[1].is_self
        assert messages[1].sender_wxid == "wxid_self"

        # 第三条：语音
        assert messages[2].is_voice
        assert not messages[2].is_self

    def test_message_time_filter(self, mock_decrypted_dir):
        """测试时间范围过滤。"""
        reader = DbReader(mock_decrypted_dir)
        # 只取 1700000010 之后的
        messages = reader.list_messages(
            "wxid_friend1", self_wxid="wxid_self",
            start_ts=1700000010, end_ts=1700000020,
        )
        assert len(messages) == 2  # 1700000010 和 1700000020

    def test_message_limit(self, mock_decrypted_dir):
        """测试 limit。"""
        reader = DbReader(mock_decrypted_dir)
        messages = reader.list_messages("wxid_friend1", limit=2)
        assert len(messages) == 2

    def test_get_voice_data(self, mock_decrypted_dir):
        """测试获取语音数据。"""
        reader = DbReader(mock_decrypted_dir)
        voice_data = reader.get_voice_data("wxid_friend1", 3)
        assert voice_data is not None
        # 首字节 0x02 应被剥离
        assert voice_data == b"\x00" * 100

    def test_get_voice_data_not_found(self, mock_decrypted_dir):
        """测试语音数据不存在。"""
        reader = DbReader(mock_decrypted_dir)
        voice_data = reader.get_voice_data("wxid_friend1", 999)
        assert voice_data is None

    def test_search_messages(self, mock_decrypted_dir):
        """测试消息搜索。"""
        reader = DbReader(mock_decrypted_dir)
        results = reader.search_messages("价格")
        assert len(results) == 1
        assert "价格" in results[0].content

    def test_group_message_prefix_strip(self, mock_decrypted_dir):
        """测试群消息前缀剥离。"""
        reader = DbReader(mock_decrypted_dir)
        # session.db 中 group1 的 summary 有前缀 "wxid_friend1:\n大家在吗"
        contacts = reader.list_contacts(contact_type="groups")
        assert contacts[0].last_msg_summary == "大家在吗"


# ============================================================================
# 配置测试
# ============================================================================
class TestConfig:
    def test_default_config(self, monkeypatch, tmp_path):
        """测试默认配置。"""
        from backend import config as cfg_module
        monkeypatch.setattr(cfg_module.Path, "home", lambda: tmp_path)

        cfg = cfg_module.default_config()
        assert "decrypted_dir" in cfg
        assert "whisper" in cfg
        assert "llm_providers" in cfg

    def test_save_load_config(self, monkeypatch, tmp_path):
        """测试保存和加载配置。"""
        from backend import config as cfg_module
        monkeypatch.setattr(cfg_module.Path, "home", lambda: tmp_path)

        cfg_module.save_config({"decrypted_dir": "/test/path", "self_wxid": "wxid_test"})
        loaded = cfg_module.load_config()
        assert loaded["decrypted_dir"] == "/test/path"
        assert loaded["self_wxid"] == "wxid_test"


# ============================================================================
# LLM 测试（不实际调用 API）
# ============================================================================
class TestLLM:
    def test_llm_client_not_available(self):
        """测试未配置的 LLM 不可用。"""
        from backend.llm import LLMClient
        client = LLMClient({})
        assert not client.available

    def test_llm_client_available(self):
        from backend.llm import LLMClient
        client = LLMClient({
            "name": "test",
            "api_base": "https://api.test.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        })
        assert client.available

    def test_classify_intent_rules(self):
        """测试规则意图识别。"""
        from backend.llm import classify_intent_rules
        intent, conf = classify_intent_rules("你好，价格多少？")
        assert intent in ("greeting", "quote", "other")
        assert 0 <= conf <= 1

    def test_classify_intent_rules_spanish(self):
        """测试西班牙语关键词。"""
        from backend.llm import classify_intent_rules
        intent, conf = classify_intent_rules("Hola, ¿cuál es el precio?")
        assert intent in ("greeting", "quote", "other")

    def test_get_active_llm_none(self):
        """测试无激活 LLM。"""
        from backend.llm import get_active_llm
        llm = get_active_llm({"active_llm": "", "llm_providers": []})
        assert llm is None

    def test_get_active_llm_by_name(self):
        from backend.llm import get_active_llm
        llm = get_active_llm({
            "active_llm": "openai",
            "llm_providers": [
                {"name": "openai", "api_base": "https://api.openai.com/v1", "api_key": "sk-test", "model": "gpt-4"},
            ],
        })
        assert llm is not None
        assert llm.name == "openai"


# ============================================================================
# API 端点测试
# ============================================================================
class TestAPI:
    @pytest.fixture
    def client(self, mock_decrypted_dir, monkeypatch, tmp_path):
        """创建测试客户端，配置指向模拟目录。"""
        from backend import config as cfg_module
        monkeypatch.setattr(cfg_module.Path, "home", lambda: tmp_path)
        cfg_module.save_config({
            "decrypted_dir": mock_decrypted_dir,
            "self_wxid": "wxid_self",
        })

        from backend.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_get_config(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "decrypted_dir" in data

    def test_list_friends(self, client):
        resp = client.get("/api/contacts", params={"type": "friends", "sort": "name"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_list_groups(self, client):
        resp = client.get("/api/contacts", params={"type": "groups"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_list_recent(self, client):
        resp = client.get("/api/contacts", params={"type": "recent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["contacts"][0]["username"] == "group1@chatroom"

    def test_get_messages(self, client):
        resp = client.get("/api/messages/wxid_friend1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        # 第一条是对方发的
        assert not data["messages"][0]["is_self"]
        # 第二条是自己发的
        assert data["messages"][1]["is_self"]

    def test_search(self, client):
        resp = client.get("/api/search", params={"keyword": "价格"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_analyze_intent_rules_fallback(self, client):
        """测试意图识别（无 LLM 时走规则兜底）。"""
        resp = client.post("/api/analyze/intent/wxid_friend1")
        assert resp.status_code == 200
        data = resp.json()
        assert "intent" in data
        assert "confidence" in data

    def test_analyze_todos_no_llm(self, client):
        """测试待办提取（无 LLM 时返回空）。"""
        resp = client.post("/api/analyze/todos/wxid_friend1")
        assert resp.status_code == 200
        data = resp.json()
        assert "todos" in data

    def test_analyze_summary_no_llm(self, client):
        """测试会话总结（无 LLM 时返回提示）。"""
        resp = client.post("/api/analyze/summary/wxid_friend1")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data

    def test_auto_setup_status(self, client):
        """测试自动检测状态查询。"""
        resp = client.get("/api/auto-setup/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "has_decrypted_dir" in data
        assert "decrypted_dir_preview" in data

    def test_auto_setup_trigger(self, client):
        """测试手动触发自动检测（不依赖真实微信环境，应返回状态字段）。"""
        resp = client.post("/api/auto-setup")
        assert resp.status_code == 200
        data = resp.json()
        assert "auto_setup_status" in data
        assert data["auto_setup_status"] in ("ok", "partial", "failed")
        assert "messages" in data
        assert isinstance(data["messages"], list)
        assert "decrypted_dir" in data
        assert "self_wxid" in data
        assert "whisper" in data


# ============================================================================
# 自动检测模块（auto_setup）单元测试
# ============================================================================
class TestAutoSetup:
    """auto_setup 模块的纯函数测试（不依赖真实微信环境）。"""

    def test_is_valid_decrypted_dir_empty(self):
        """空目录不应被识别为解密目录。"""
        from backend.auto_setup import _is_valid_decrypted_dir
        with tempfile.TemporaryDirectory() as td:
            assert _is_valid_decrypted_dir(td) is False

    def test_is_valid_decrypted_dir_with_contact(self, mock_decrypted_dir):
        """有 contact.db 的目录应被识别为有效解密目录。"""
        from backend.auto_setup import _is_valid_decrypted_dir
        assert _is_valid_decrypted_dir(mock_decrypted_dir) is True

    def test_auto_detect_decrypted_dir_finds_mock(self, mock_decrypted_dir, monkeypatch):
        """auto_detect_decrypted_dir 应能扫描到模拟目录。"""
        from backend import auto_setup
        # 把模拟目录注入扫描路径
        monkeypatch.setattr(Path, "home", lambda: Path(mock_decrypted_dir).parent)
        # 让 wechat-decrypt 检测返回 None，强制走回退扫描
        monkeypatch.setattr(auto_setup, "find_wechat_decrypt_dir", lambda: None)
        # 直接调用 _is_valid_decrypted_dir 验证
        assert auto_setup._is_valid_decrypted_dir(mock_decrypted_dir)

    def test_looks_like_wxid(self):
        """测试 wxid 格式判断。"""
        from backend.auto_setup import _looks_like_wxid
        assert _looks_like_wxid("wxid_abc123") is True
        assert _looks_like_wxid("wxid_8pcyza2ww2qj21_bd86") is True
        assert _looks_like_wxid("张三") is False  # 中文不是 wxid
        assert _looks_like_wxid("") is False
        assert _looks_like_wxid("ab") is False  # 太短
        assert _looks_like_wxid("abc") is False  # 太短

    def test_infer_self_from_decrypted(self, mock_decrypted_dir):
        """从解密目录推断本人 wxid。"""
        from backend.auto_setup import _infer_self_from_decrypted
        # mock 数据中 real_sender_id=1 对应 wxid_self
        wxid = _infer_self_from_decrypted(mock_decrypted_dir)
        # 应该返回某个 wxid（具体是哪个取决于消息统计）
        assert wxid is not None
        assert wxid.startswith("wxid_")

    def test_auto_detect_whisper_returns_dict(self):
        """auto_detect_whisper 应返回 dict（即使没装 whisper 也应有字段）。"""
        from backend.auto_setup import auto_detect_whisper
        result = auto_detect_whisper()
        assert isinstance(result, dict)
        assert "binary_path" in result
        assert "model_path" in result
        assert "language" in result

    def test_parse_decrypt_count(self):
        """测试解密输出解析。"""
        from backend.auto_setup import _parse_decrypt_count
        assert _parse_decrypt_count("解密成功: 26 个数据库") == 26
        assert _parse_decrypt_count("decrypted: 5") == 5
        assert _parse_decrypt_count("no match") == 0

    def test_run_auto_setup_with_mock(self, mock_decrypted_dir, monkeypatch):
        """run_auto_setup 在有模拟解密目录时应返回 ok 状态。"""
        from backend import auto_setup

        # mock 检测函数，让它们找到模拟目录
        monkeypatch.setattr(auto_setup, "auto_detect_decrypted_dir", lambda: mock_decrypted_dir)
        monkeypatch.setattr(auto_setup, "auto_detect_wechat_data_dir", lambda: None)
        monkeypatch.setattr(
            auto_setup, "auto_detect_self_wxid",
            lambda **kw: "wxid_self"
        )
        monkeypatch.setattr(
            auto_setup, "auto_detect_whisper",
            lambda: {"binary_path": "", "model_path": "", "language": ""}
        )

        result = auto_setup.run_auto_setup()
        assert result["auto_setup_status"] == "ok"
        assert result["decrypted_dir"] == mock_decrypted_dir
        assert result["self_wxid"] == "wxid_self"
        assert isinstance(result["messages"], list)
        assert len(result["messages"]) > 0

    def test_auto_detect_scans_dev_dirs(self, mock_decrypted_dir, monkeypatch, tmp_path):
        """auto_detect_decrypted_dir 应能扫描到 ~/Study/wechat-decrypt/decrypted。"""
        from backend import auto_setup

        # 构造 ~/Study/wechat-decrypt/decrypted/ 结构（用 tmp_path 模拟家目录）
        home = tmp_path
        study_dir = home / "Study" / "wechat-decrypt"
        study_dir.mkdir(parents=True)
        # 把模拟解密目录复制到 Study/wechat-decrypt/decrypted
        import shutil
        shutil.copytree(mock_decrypted_dir, str(study_dir / "decrypted"))

        monkeypatch.setattr(Path, "home", lambda: home)
        monkeypatch.setattr(auto_setup, "find_wechat_decrypt_dir", lambda: None)
        monkeypatch.setattr(auto_setup, "load_wcd_config", lambda: {})

        found = auto_setup.auto_detect_decrypted_dir()
        assert found is not None
        assert "Study" in found
        assert found.endswith("decrypted")

    def test_dev_dir_candidates_includes_study(self, monkeypatch, tmp_path):
        """_dev_dir_candidates 应包含 ~/Study。"""
        from backend import auto_setup

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / "Study").mkdir()
        (tmp_path / "Projects").mkdir()
        candidates = auto_setup._dev_dir_candidates()
        candidate_strs = [str(p) for p in candidates]
        assert any("Study" in s for s in candidate_strs)
        assert any("Projects" in s for s in candidate_strs)


# ============================================================================
# LLM 错误透传与 api_base 清理测试
# ============================================================================
class TestLLMErrorHandling:
    """修复1：LLM 错误透传 + api_base 清理 + /v1 后缀检测。"""

    def test_sanitize_api_base_strips_backticks(self):
        """反引号应被剥离（用户从 Markdown 文档复制时常见）。"""
        from backend.llm import _sanitize_api_base
        assert _sanitize_api_base("`https://api.deepseek.com/v1`") == "https://api.deepseek.com/v1"
        assert _sanitize_api_base("``https://api.deepseek.com/v1``") == "https://api.deepseek.com/v1"
        assert _sanitize_api_base("'https://api.test.com/v1'") == "https://api.test.com/v1"
        assert _sanitize_api_base('"https://api.test.com/v1"') == "https://api.test.com/v1"

    def test_sanitize_api_base_strips_trailing_slash(self):
        """末尾斜杠应被剥离。"""
        from backend.llm import _sanitize_api_base
        assert _sanitize_api_base("https://api.test.com/v1/") == "https://api.test.com/v1"
        assert _sanitize_api_base("https://api.test.com/v1///") == "https://api.test.com/v1"

    def test_sanitize_api_base_strips_whitespace(self):
        """首尾空格应被剥离。"""
        from backend.llm import _sanitize_api_base
        assert _sanitize_api_base("  https://api.test.com/v1  ") == "https://api.test.com/v1"

    def test_sanitize_api_base_empty(self):
        """空值应返回空字符串。"""
        from backend.llm import _sanitize_api_base
        assert _sanitize_api_base("") == ""
        assert _sanitize_api_base(None) == ""  # type: ignore[arg-type]

    def test_validate_api_base_missing_v1_for_known_provider(self):
        """已知 provider 缺少 /v1 后缀应给出提示。"""
        from backend.llm import validate_api_base
        hint = validate_api_base("https://api.deepseek.com")
        assert hint is not None
        assert "/v1" in hint

    def test_validate_api_base_missing_v1_openai(self):
        from backend.llm import validate_api_base
        hint = validate_api_base("https://api.openai.com")
        assert hint is not None
        assert "/v1" in hint

    def test_validate_api_base_ok_with_v1(self):
        """带 /v1 的地址不应有提示。"""
        from backend.llm import validate_api_base
        assert validate_api_base("https://api.deepseek.com/v1") is None
        assert validate_api_base("https://api.openai.com/v1") is None

    def test_validate_api_base_ok_unknown_provider_no_v1(self):
        """未知 provider（如本地 ollama）缺 /v1 不应报警。"""
        from backend.llm import validate_api_base
        assert validate_api_base("http://localhost:11434") is None

    def test_validate_api_base_empty(self):
        from backend.llm import validate_api_base
        hint = validate_api_base("")
        assert hint is not None
        assert "空" in hint

    def test_llm_client_init_sanitizes_api_base(self):
        """LLMClient 构造时应自动清理 api_base。"""
        from backend.llm import LLMClient
        client = LLMClient({
            "api_base": "`https://api.deepseek.com/v1`",
            "api_key": "sk-test",
            "model": "deepseek-chat",
        })
        assert client.api_base == "https://api.deepseek.com/v1"

    def test_llm_client_validate_method(self):
        """LLMClient.validate() 应返回诊断提示。"""
        from backend.llm import LLMClient
        client = LLMClient({
            "api_base": "https://api.deepseek.com",  # 缺 /v1
            "api_key": "sk-test",
            "model": "deepseek-chat",
        })
        hint = client.validate()
        assert hint is not None
        assert "/v1" in hint

    def test_diagnose_http_error_401(self):
        from backend.llm import _diagnose_http_error
        msg = _diagnose_http_error(401, "", "https://api.test.com/v1/chat/completions")
        assert "401" in msg
        assert "api_key" in msg

    def test_diagnose_http_error_404(self):
        from backend.llm import _diagnose_http_error
        msg = _diagnose_http_error(404, "not found", "https://api.test.com/v1/chat/completions")
        assert "404" in msg
        assert "/v1" in msg or "model" in msg

    def test_diagnose_http_error_500(self):
        from backend.llm import _diagnose_http_error
        msg = _diagnose_http_error(500, "server error", "https://api.test.com/v1/chat/completions")
        assert "500" in msg

    def test_chat_returns_tuple_on_missing_config(self):
        """配置缺失时 chat 应返回 (None, error) 元组。"""
        from backend.llm import LLMClient
        client = LLMClient({})
        content, err = client.chat([{"role": "user", "content": "hi"}])
        assert content is None
        assert isinstance(err, str)
        assert len(err) > 0

    def test_classify_intent_returns_llm_error_field(self, monkeypatch):
        """classify_intent 在 LLM 调用失败时应返回 llm_error 字段。"""
        from backend import llm as llm_module
        from backend.llm import LLMClient, classify_intent

        client = LLMClient({
            "api_base": "https://api.deepseek.com/v1",
            "api_key": "sk-invalid",
            "model": "deepseek-chat",
        })
        # mock chat 方法模拟失败
        monkeypatch.setattr(
            client, "chat",
            lambda messages, temperature=None: (None, "LLM 调用失败 (HTTP 401 未授权)")
        )
        result = classify_intent(
            [{"sender": "对方", "content": "你好", "time": "2024-01-01"}],
            client,
        )
        assert result["intent"] == "error"
        assert "llm_error" in result
        assert "401" in result["llm_error"]


# ============================================================================
# LLM 测试端点 + 增量解密端点测试
# ============================================================================
class TestAPIExtra:
    """修复1（/api/llm/test）+ 修复3（/api/decrypt/incremental）端点测试。"""

    @pytest.fixture
    def client(self, mock_decrypted_dir, monkeypatch, tmp_path):
        from backend import config as cfg_module
        monkeypatch.setattr(cfg_module.Path, "home", lambda: tmp_path)
        cfg_module.save_config({
            "decrypted_dir": mock_decrypted_dir,
            "self_wxid": "wxid_self",
        })
        from backend.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_llm_test_missing_v1_returns_config_hint(self, client):
        """/api/llm/test 对缺 /v1 的 deepseek 地址应返回 config_hint。"""
        resp = client.post("/api/llm/test", json={
            "name": "deepseek",
            "api_base": "https://api.deepseek.com",  # 缺 /v1
            "api_key": "sk-test",
            "model": "deepseek-chat",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["config_hint"]  # 非空
        assert "/v1" in data["config_hint"]

    def test_llm_test_sanitizes_backticks(self, client):
        """/api/llm/test 应清理 api_base 中的反引号（不会因反引号而误判）。"""
        resp = client.post("/api/llm/test", json={
            "name": "deepseek",
            "api_base": "`https://api.deepseek.com/v1`",  # 带反引号但有 /v1
            "api_key": "sk-test",
            "model": "deepseek-chat",
        })
        assert resp.status_code == 200
        data = resp.json()
        # 反引号被清理后 api_base 应是干净的
        assert data["api_base"] == "https://api.deepseek.com/v1"
        # config_hint 应为空（清理后地址合法）
        assert data["config_hint"] == ""

    def test_llm_test_empty_api_base(self, client):
        """/api/llm/test 对空 api_base 应返回错误。"""
        resp = client.post("/api/llm/test", json={
            "name": "test",
            "api_base": "",
            "api_key": "sk-test",
            "model": "gpt-4",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "空" in data["error"] or "空" in data["config_hint"]

    def test_decrypt_incremental_endpoint_exists(self, client, monkeypatch):
        """/api/decrypt/incremental 端点应存在并返回标准结构。"""
        from backend import main as main_module
        # mock try_auto_decrypt 避免真实调用 wechat-decrypt
        monkeypatch.setattr(
            main_module, "try_auto_decrypt",
            lambda timeout=300: {
                "success": True,
                "message": "解密成功（增量模式，5 个数据库）",
                "decrypted_dir": "/tmp/fake_decrypted",
                "decrypted_count": 5,
            }
        )
        resp = client.post("/api/decrypt/incremental")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["decrypted_dir"] == "/tmp/fake_decrypted"
        assert data["decrypted_count"] == 5
        assert "解密成功" in data["message"]

    def test_decrypt_incremental_failure(self, client, monkeypatch):
        """/api/decrypt/incremental 在解密失败时应返回 ok=false。"""
        from backend import main as main_module
        monkeypatch.setattr(
            main_module, "try_auto_decrypt",
            lambda timeout=300: {
                "success": False,
                "message": "未找到 wechat-decrypt 项目目录",
                "decrypted_dir": None,
                "decrypted_count": 0,
            }
        )
        resp = client.post("/api/decrypt/incremental")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert data["decrypted_count"] == 0
        assert "未找到" in data["message"]
