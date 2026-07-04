"""本地存储层。

对外暴露：
- Database / get_default_db：连接管理
- Repository：所有 CRUD 操作
- 各数据模型
"""

from .db import Database, get_default_db, reset_default_db
from .models import (
    AssistantTurn,
    Contact,
    Message,
    MessageSearchResult,
    QueryFilter,
    Setting,
    Todo,
)
from .repository import (
    Repository,
    matched_ids_str,
    parse_matched_ids,
    query_filter_to_text,
)

__all__ = [
    "Database",
    "Repository",
    "get_default_db",
    "reset_default_db",
    "Contact",
    "Message",
    "Todo",
    "AssistantTurn",
    "Setting",
    "QueryFilter",
    "MessageSearchResult",
    "query_filter_to_text",
    "matched_ids_str",
    "parse_matched_ids",
]
