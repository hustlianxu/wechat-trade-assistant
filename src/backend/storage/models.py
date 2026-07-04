"""数据模型（Pydantic v2），用于在模块/接口之间传递结构化数据。

注意：这些模型与 schema.sql 的字段一一对应，但与 sqlite3.Row 解耦，
方便其他模块（如 mcp、todo）使用，也方便 FastAPI 序列化。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Contact(BaseModel):
    id: Optional[int] = None
    wxid: str
    nickname: str = ""
    remark: str = ""
    alias: str = ""
    region: str = ""
    last_intent: str = ""
    last_intent_ts: Optional[int] = None
    last_msg_ts: Optional[int] = None
    note: str = ""
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class Message(BaseModel):
    id: Optional[int] = None
    contact_id: int
    msg_id: Optional[str] = None
    msg_type: str = "text"  # text/image/voice/system/file/other
    direction: str = "in"  # in / out
    sender: str = ""
    content: str = ""
    raw_path: str = ""
    thumb_path: str = ""
    transcribed: bool = False
    intent: str = ""
    confidence: float = 0.0
    created_ts: int
    ingested_ts: Optional[int] = None


class Todo(BaseModel):
    id: Optional[int] = None
    contact_id: Optional[int] = None
    message_id: Optional[int] = None
    title: str
    detail: str = ""
    due_ts: Optional[int] = None
    status: str = "pending"  # pending/doing/done/cancelled
    source: str = "manual"  # manual / auto_extract
    priority: str = "normal"  # low/normal/high/urgent
    created_ts: Optional[int] = None
    updated_ts: Optional[int] = None
    completed_ts: Optional[int] = None


class AssistantTurn(BaseModel):
    id: Optional[int] = None
    role: str  # user / assistant
    content: str
    parsed_query: str = ""
    matched_msg_ids: str = ""
    latency_ms: int = 0
    engine: str = "local"  # local / cloud
    created_ts: Optional[int] = None


class Setting(BaseModel):
    key: str
    value: str = ""


# ============================================================================
# 查询参数模型：MCP 模块解析后的结构化查询条件
# ============================================================================
class QueryFilter(BaseModel):
    """MCP 自然语言解析后产出的结构化查询条件。

    所有字段均可空，表示该条件不约束。
    """

    contact_ids: List[int] = Field(default_factory=list)
    contact_keywords: List[str] = Field(default_factory=list)  # 客户名/备注模糊匹配
    keywords: List[str] = Field(default_factory=list)  # 消息内容关键词
    intents: List[str] = Field(default_factory=list)  # 意图过滤
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    relative_time: Optional[str] = None  # 原始时间短语，如 "上周"、"最近一个月"
    msg_types: List[str] = Field(default_factory=list)
    include_todos: bool = False  # 是否同时查询待办
    todo_status: Optional[str] = None  # 待办状态过滤
    intent_action: Optional[str] = None  # "compare" / "summarize" / "list" / "answer"
    raw_query: str = ""  # 原始用户输入


class MessageSearchResult(BaseModel):
    """查询返回的结果。"""

    messages: List[Message] = Field(default_factory=list)
    contacts: List[Contact] = Field(default_factory=list)
    todos: List[Todo] = Field(default_factory=list)
    summary: str = ""  # 本地或云端生成的摘要
    engine: str = "local"  # local / cloud
    latency_ms: int = 0
