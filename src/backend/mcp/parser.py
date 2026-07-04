"""MCP 自然语言查询解析器。

把用户的自然语言提问转换为 QueryFilter，供 retriever 检索本地数据库。

输入示例：
  "帮我查一下上周和 Juan 的聊天，总结一下他的订单需求"
  → QueryFilter(contact_keywords=['Juan'], relative_time='上周',
              keywords=['订单'], intent_action='summarize')

  "对比 Maria 和 Carlos 最近一个月关于价格的讨论"
  → QueryFilter(contact_keywords=['Maria','Carlos'],
              relative_time='近30天', keywords=['价格'],
              intent_action='compare')

  "把昨天所有未处理的待办列出来"
  → QueryFilter(relative_time='昨天', include_todos=True,
              todo_status='pending', intent_action='list')
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..storage.models import QueryFilter
from . import ner


class QueryParser:
    """自然语言 → QueryFilter 解析器。

    纯本地、无依赖，可单测。
    """

    def __init__(self, known_contact_names: Optional[List[str]] = None) -> None:
        # 已知客户名（备注/昵称），用于辅助联系人识别
        self.known_contact_names = list(known_contact_names or [])

    def update_known_contacts(self, names: List[str]) -> None:
        """刷新已知客户名（每次启动或导入新数据后调用）。"""
        self.known_contact_names = [n for n in names if n]

    def parse(self, text: str, now: Optional[datetime] = None) -> QueryFilter:
        """解析自然语言，返回 QueryFilter。"""
        entities = ner.parse(
            text,
            known_contacts=self.known_contact_names,
            now=now,
        )
        return QueryFilter(
            contact_keywords=entities.contact_keywords,
            keywords=entities.keywords,
            intents=entities.intents,
            start_ts=entities.start_ts,
            end_ts=entities.end_ts,
            relative_time=entities.relative_time,
            include_todos=entities.include_todos,
            todo_status=entities.todo_status,
            intent_action=entities.intent_action,
            raw_query=text,
        )


# 模块级单例
_default_parser: Optional[QueryParser] = None


def get_default_parser() -> QueryParser:
    global _default_parser
    if _default_parser is None:
        _default_parser = QueryParser()
    return _default_parser
