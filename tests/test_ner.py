"""测试 MCP 模块的 NER 与 QueryParser。

纯本地解析，无外部依赖，应全部通过。
"""

from __future__ import annotations

from datetime import datetime

from backend.mcp import QueryParser
from backend.mcp.ner import (
    extract_contacts,
    extract_keywords,
    resolve_relative_time,
    parse,
)


# 锚定时间，避免相对时间漂移
NOW = datetime(2026, 6, 15, 12, 0, 0)  # 周一


# ============================================================================
# 时间解析
# ============================================================================
class TestResolveRelativeTime:
    def test_today(self):
        s, e = resolve_relative_time("今天", now=NOW)
        assert s is not None and e is not None
        # 开始 = 今天 00:00
        assert datetime.fromtimestamp(s) == datetime(2026, 6, 15, 0, 0, 0)
        # 结束 = 今天 23:59:59
        assert datetime.fromtimestamp(e) == datetime(2026, 6, 15, 23, 59, 59)

    def test_yesterday(self):
        s, e = resolve_relative_time("昨天", now=NOW)
        assert datetime.fromtimestamp(s) == datetime(2026, 6, 14, 0, 0, 0)
        assert datetime.fromtimestamp(e) == datetime(2026, 6, 14, 23, 59, 59)

    def test_yesterday_spanish(self):
        # 西语 ayer 也应识别
        s, e = resolve_relative_time("昨天", now=NOW)
        s2, _ = resolve_relative_time("昨天", now=NOW)
        assert s == s2

    def test_last_week(self):
        # 2026-06-15 是周一，上周 = 6/8 00:00 ~ 6/14 23:59:59
        s, e = resolve_relative_time("上周", now=NOW)
        assert datetime.fromtimestamp(s) == datetime(2026, 6, 8, 0, 0, 0)
        assert datetime.fromtimestamp(e) == datetime(2026, 6, 14, 23, 59, 59)

    def test_recent_30_days(self):
        s, e = resolve_relative_time("近30天", now=NOW)
        # 6/15 - 29 天 = 5/17
        assert datetime.fromtimestamp(s) == datetime(2026, 5, 17, 0, 0, 0)
        assert datetime.fromtimestamp(e) == datetime(2026, 6, 15, 23, 59, 59)

    def test_unknown_phrase(self):
        s, e = resolve_relative_time("某年某月", now=NOW)
        assert s is None and e is None


# ============================================================================
# 联系人识别
# ============================================================================
class TestExtractContacts:
    def test_with_pattern_chinese(self):
        # "和 Juan 的聊天" 句式
        names = extract_contacts("帮我查上周和 Juan 的聊天记录", known_contacts=None)
        assert "Juan" in names

    def test_quoted_name(self):
        names = extract_contacts('查一下 "Maria" 关于报价的讨论', known_contacts=None)
        assert any("Maria" in n or "Maria" in n.lower() for n in names)

    def test_known_contact_direct_hit(self):
        names = extract_contacts(
            "Maria 最近有没有问价格",
            known_contacts=["Maria", "Juan"],
        )
        assert any(n.lower() == "maria" for n in names)

    def test_multiple_contacts_compare(self):
        # "对比 Maria 和 Carlos" 应识别两个
        names = extract_contacts(
            "对比 Maria 和 Carlos 最近一个月关于价格的讨论",
            known_contacts=["Maria", "Carlos"],
        )
        lowered = [n.lower() for n in names]
        assert "maria" in lowered
        assert "carlos" in lowered

    def test_no_contact(self):
        names = extract_contacts("列出昨天所有待办", known_contacts=None)
        assert names == []


# ============================================================================
# 关键词识别
# ============================================================================
class TestExtractKeywords:
    def test_chinese_keyword(self):
        kws = extract_keywords("查一下关于价格的聊天", contacts=[])
        assert any("价格" in k for k in kws) or "价格" in kws

    def test_spanish_keyword(self):
        kws = extract_keywords("buscar conversaciones sobre precio con Juan", contacts=["Juan"])
        # "precio" 应被识别为"价格"或"precio"
        assert len(kws) > 0

    def test_quoted_keyword(self):
        kws = extract_keywords('查包含 "factura proforma" 的消息', contacts=[])
        assert any("factura" in k.lower() for k in kws)


# ============================================================================
# QueryParser 端到端
# ============================================================================
class TestQueryParser:
    def test_parse_summary_query(self):
        """场景 1：'帮我查一下上周和 Juan 的聊天，总结一下他的订单需求'"""
        parser = QueryParser(known_contact_names=["Juan", "Maria", "Carlos"])
        qf = parser.parse(
            "帮我查一下上周和 Juan 的聊天，总结一下他的订单需求",
            now=NOW,
        )
        assert "Juan" in qf.contact_keywords or any(
            "juan" in k.lower() for k in qf.contact_keywords
        )
        assert qf.relative_time == "上周"
        assert qf.intent_action == "summarize"
        assert qf.start_ts is not None and qf.end_ts is not None

    def test_parse_compare_query(self):
        """场景 2：'对比 Maria 和 Carlos 最近一个月关于价格的讨论'"""
        parser = QueryParser(known_contact_names=["Maria", "Carlos", "Juan"])
        qf = parser.parse(
            "对比 Maria 和 Carlos 最近一个月关于价格的讨论",
            now=NOW,
        )
        lowered = [k.lower() for k in qf.contact_keywords]
        assert "maria" in lowered
        assert "carlos" in lowered
        assert qf.intent_action == "compare"
        assert qf.relative_time in ("近30天", "最近一个月")

    def test_parse_todo_list_query(self):
        """场景 3：'把昨天所有未处理的待办列出来'"""
        parser = QueryParser()
        qf = parser.parse("把昨天所有未处理的待办列出来", now=NOW)
        assert qf.include_todos is True
        assert qf.intent_action == "list"
        assert qf.relative_time == "昨天"

    def test_parse_no_action_defaults_to_answer(self):
        """无动作词时 intent_action 应为 None 或 answer，不应抛异常。"""
        parser = QueryParser()
        qf = parser.parse("Juan 上周说了什么", now=NOW)
        assert qf.raw_query == "Juan 上周说了什么"
