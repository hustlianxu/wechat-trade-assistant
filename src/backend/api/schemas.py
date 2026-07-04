"""API 请求/响应 Schema（Pydantic）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 通用
# ============================================================================
class ErrorResponse(BaseModel):
    error: str
    detail: str = ""


class OkResponse(BaseModel):
    ok: bool = True
    message: str = ""


# ============================================================================
# 仪表盘
# ============================================================================
class DashboardData(BaseModel):
    today_todo_count: int = 0
    pending_todo_count: int = 0
    unread_intent_contacts: int = 0
    recent_contacts: List[Dict[str, Any]] = Field(default_factory=list)
    recent_todos: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# 联系人
# ============================================================================
class ContactOut(BaseModel):
    id: int
    wxid: str
    nickname: str = ""
    remark: str = ""
    alias: str = ""
    region: str = ""
    last_intent: str = ""
    last_intent_ts: Optional[int] = None
    last_msg_ts: Optional[int] = None
    note: str = ""


class ContactListResponse(BaseModel):
    contacts: List[ContactOut]
    total: int


# ============================================================================
# 消息
# ============================================================================
class MessageOut(BaseModel):
    id: int
    contact_id: int
    msg_id: Optional[str] = None
    msg_type: str = "text"
    direction: str = "in"
    sender: str = ""
    content: str = ""
    thumb_path: str = ""
    transcribed: bool = False
    intent: str = ""
    confidence: float = 0.0
    created_ts: int


class MessageListResponse(BaseModel):
    messages: List[MessageOut]
    total: int


class SearchMessagesRequest(BaseModel):
    contact_id: Optional[int] = None
    contact_keyword: Optional[str] = None
    keyword: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    msg_type: Optional[str] = None
    limit: int = 200


# ============================================================================
# 意图
# ============================================================================
class IntentLabelRequest(BaseModel):
    text: str


class IntentLabelResponse(BaseModel):
    intent: str
    confidence: float


class BatchIntentRequest(BaseModel):
    texts: List[str]


class BatchIntentResponse(BaseModel):
    results: List[IntentLabelResponse]


# ============================================================================
# 待办
# ============================================================================
class TodoOut(BaseModel):
    id: int
    contact_id: Optional[int] = None
    message_id: Optional[int] = None
    title: str
    detail: str = ""
    due_ts: Optional[int] = None
    status: str = "pending"
    source: str = "manual"
    priority: str = "normal"
    created_ts: Optional[int] = None
    updated_ts: Optional[int] = None
    completed_ts: Optional[int] = None


class TodoListResponse(BaseModel):
    todos: List[TodoOut]
    total: int


class TodoCreateRequest(BaseModel):
    title: str
    contact_id: Optional[int] = None
    detail: str = ""
    due_ts: Optional[int] = None
    priority: str = "normal"


class TodoUpdateRequest(BaseModel):
    title: Optional[str] = None
    detail: Optional[str] = None
    due_ts: Optional[int] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    contact_id: Optional[int] = None


class TodoSummaryResponse(BaseModel):
    by_status: Dict[str, int]
    by_contact: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# 智能助手（MCP）
# ============================================================================
class AssistantQueryRequest(BaseModel):
    """自然语言查询请求。

    text: 用户的自然语言提问
    use_cloud: 是否强制使用云端 LLM（若未配置则忽略）
    """

    text: str
    use_cloud: bool = False


class AssistantMessageOut(BaseModel):
    id: Optional[int] = None
    role: str
    content: str
    parsed_query: str = ""
    matched_msg_ids: str = ""
    latency_ms: int = 0
    engine: str = "local"
    created_ts: Optional[int] = None
    # 附加的结构化结果
    messages: List[MessageOut] = Field(default_factory=list)
    contacts: List[ContactOut] = Field(default_factory=list)
    todos: List[TodoOut] = Field(default_factory=list)


class AssistantHistoryResponse(BaseModel):
    turns: List[AssistantMessageOut]


# ============================================================================
# 设置
# ============================================================================
class SettingsResponse(BaseModel):
    wechat_version: str = ""
    wechat_generation: str = ""
    wechat_data_dirs: List[str] = Field(default_factory=list)
    needs_resign: bool = False
    is_resigned: bool = False
    realtime_listen: bool = False
    llm_api_base: str = ""
    llm_model: str = ""
    llm_api_key_set: bool = False
    whisper_available: bool = False
    intent_model_available: bool = False
    db_path: str = ""
    data_dir: str = ""


class LLMConfigRequest(BaseModel):
    api_base: str
    api_key: str
    model: str
    timeout: float = 30.0


class RealtimeListenRequest(BaseModel):
    enabled: bool


class ManualKeyRequest(BaseModel):
    key_hex: str


class ResignRequest(BaseModel):
    password: Optional[str] = None


# ============================================================================
# 解密 / 导入
# ============================================================================
class DecryptStatusResponse(BaseModel):
    wechat_detected: bool
    wechat_version: str = ""
    wechat_generation: str = ""
    needs_resign: bool = False
    needs_admin: bool = False
    data_dirs: List[str] = Field(default_factory=list)
    last_decrypt_run: Optional[Dict[str, Any]] = None


class DecryptTriggerRequest(BaseModel):
    """手动触发解密导入。"""

    source: str = "auto"  # auto / memory / registry / manual
    manual_key: Optional[str] = None
    wxid: Optional[str] = None  # 多账号时指定


class DecryptTriggerResponse(BaseModel):
    ok: bool
    message: str
    msg_count: int = 0
    contact_count: int = 0
