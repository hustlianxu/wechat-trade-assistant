"""FastAPI 路由：暴露所有功能给前端 Electron 调用。

所有路径以 /api 为前缀。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, HTTPException

from ..config import get_repo, get_models_dir, get_bin_dir, get_app_data_dir
from ..decrypt import (
    KeyExtractionError,
    PollingListener,
    SSEConfig,
    detect_installed_wechat,
    extract_key,
    find_msg_db,
    find_micro_msg_db,
    find_wechat_data_dirs,
    is_resigned,
    iter_contacts,
    iter_messages,
    needs_resign,
    open_decrypted_db,
    perform_resign,
    to_contact_model,
    to_message_model,
    validate_manual_key,
)
from ..intent import classify as intent_classify
from ..intent import classify_batch as intent_classify_batch
from ..mcp import (
    CloudLLMConfig,
    QueryParser,
    Responder,
)
from ..storage.models import (
    AssistantTurn,
    Contact,
    Message,
    Todo,
)
from ..storage.repository import matched_ids_str, query_filter_to_text
from ..stt import WhisperEngine, get_default_engine as get_default_stt_engine
from ..todo import TodoManager
from . import schemas


router = APIRouter(prefix="/api")


# ============================================================================
# 工具
# ============================================================================
def _contact_to_out(c: Contact) -> schemas.ContactOut:
    return schemas.ContactOut(
        id=c.id,
        wxid=c.wxid,
        nickname=c.nickname,
        remark=c.remark,
        alias=c.alias,
        region=c.region,
        last_intent=c.last_intent,
        last_intent_ts=c.last_intent_ts,
        last_msg_ts=c.last_msg_ts,
        note=c.note,
    )


def _message_to_out(m: Message) -> schemas.MessageOut:
    return schemas.MessageOut(
        id=m.id,
        contact_id=m.contact_id,
        msg_id=m.msg_id,
        msg_type=m.msg_type,
        direction=m.direction,
        sender=m.sender,
        content=m.content,
        thumb_path=m.thumb_path,
        transcribed=m.transcribed,
        intent=m.intent,
        confidence=m.confidence,
        created_ts=m.created_ts,
    )


def _todo_to_out(t: Todo) -> schemas.TodoOut:
    return schemas.TodoOut(
        id=t.id,
        contact_id=t.contact_id,
        message_id=t.message_id,
        title=t.title,
        detail=t.detail,
        due_ts=t.due_ts,
        status=t.status,
        source=t.source,
        priority=t.priority,
        created_ts=t.created_ts,
        updated_ts=t.updated_ts,
        completed_ts=t.completed_ts,
    )


def _get_responder() -> Responder:
    """根据当前 settings 构造 Responder（带可选 LLM 配置）。"""
    repo = get_repo()
    settings = repo.get_all_settings()
    llm_config = CloudLLMConfig.from_settings(settings)
    return Responder(repo, llm_config=llm_config)


def _get_parser() -> QueryParser:
    repo = get_repo()
    contacts = repo.list_contacts()
    names = []
    for c in contacts:
        for n in (c.remark, c.nickname, c.alias):
            if n:
                names.append(n)
    parser = QueryParser(known_contact_names=names)
    return parser


# ============================================================================
# 健康检查
# ============================================================================
@router.get("/health")
def health() -> dict:
    return {"ok": True, "ts": int(time.time())}


# ============================================================================
# 仪表盘
# ============================================================================
@router.get("/dashboard", response_model=schemas.DashboardData)
def dashboard() -> schemas.DashboardData:
    repo = get_repo()
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    today_end = int((datetime.now() + timedelta(days=1)).timestamp())

    pending_todos = repo.list_todos(status="pending")
    today_todos = [
        t for t in pending_todos
        if t.created_ts and today_start <= t.created_ts < today_end
    ]
    recent_contacts = [_contact_to_out(c).model_dump() for c in repo.list_contacts()[:10]]
    recent_todos = [_todo_to_out(t).model_dump() for t in pending_todos[:10]]
    unread_intent_contacts = sum(1 for c in repo.list_contacts() if c.last_intent and c.last_intent != "greeting")

    return schemas.DashboardData(
        today_todo_count=len(today_todos),
        pending_todo_count=len(pending_todos),
        unread_intent_contacts=unread_intent_contacts,
        recent_contacts=recent_contacts,
        recent_todos=recent_todos,
    )


# ============================================================================
# 联系人
# ============================================================================
@router.get("/contacts", response_model=schemas.ContactListResponse)
def list_contacts(intent: str | None = None) -> schemas.ContactListResponse:
    repo = get_repo()
    contacts = repo.list_contacts(intent=intent)
    return schemas.ContactListResponse(
        contacts=[_contact_to_out(c) for c in contacts],
        total=len(contacts),
    )


@router.get("/contacts/{contact_id}", response_model=schemas.ContactOut)
def get_contact(contact_id: int) -> schemas.ContactOut:
    repo = get_repo()
    c = repo.get_contact(contact_id)
    if c is None:
        raise HTTPException(404, "联系人不存在")
    return _contact_to_out(c)


# ============================================================================
# 消息
# ============================================================================
@router.get("/contacts/{contact_id}/messages", response_model=schemas.MessageListResponse)
def list_contact_messages(
    contact_id: int,
    start_ts: int | None = None,
    end_ts: int | None = None,
    msg_type: str | None = None,
    limit: int = 500,
) -> schemas.MessageListResponse:
    repo = get_repo()
    msgs = repo.list_messages(
        contact_id=contact_id,
        start_ts=start_ts,
        end_ts=end_ts,
        msg_type=msg_type,
        limit=limit,
    )
    return schemas.MessageListResponse(
        messages=[_message_to_out(m) for m in msgs],
        total=len(msgs),
    )


@router.post("/messages/search", response_model=schemas.MessageListResponse)
def search_messages(req: schemas.SearchMessagesRequest) -> schemas.MessageListResponse:
    """简单结构化检索（与 MCP 自然语言检索不同，这是给前端筛选用）。"""
    from ..storage.models import QueryFilter

    repo = get_repo()
    qf = QueryFilter(
        contact_ids=[req.contact_id] if req.contact_id else [],
        contact_keywords=[req.contact_keyword] if req.contact_keyword else [],
        keywords=[req.keyword] if req.keyword else [],
        start_ts=req.start_ts,
        end_ts=req.end_ts,
        msg_types=[req.msg_type] if req.msg_type else [],
        raw_query="api_search",
    )
    msgs = repo.search_messages(qf, limit=req.limit)
    return schemas.MessageListResponse(
        messages=[_message_to_out(m) for m in msgs],
        total=len(msgs),
    )


# ============================================================================
# 意图
# ============================================================================
@router.post("/intent/classify", response_model=schemas.IntentLabelResponse)
def classify_intent(req: schemas.IntentLabelRequest) -> schemas.IntentLabelResponse:
    intent, conf = intent_classify(req.text)
    return schemas.IntentLabelResponse(intent=intent, confidence=conf)


@router.post("/intent/classify/batch", response_model=schemas.BatchIntentResponse)
def classify_intent_batch(req: schemas.BatchIntentRequest) -> schemas.BatchIntentResponse:
    results = intent_classify_batch(req.texts)
    return schemas.BatchIntentResponse(
        results=[schemas.IntentLabelResponse(intent=i, confidence=c) for i, c in results]
    )


@router.post("/contacts/{contact_id}/reclassify")
def reclassify_contact_messages(contact_id: int, limit: int = 200) -> dict:
    """对该联系人的所有消息重新跑意图识别。"""
    repo = get_repo()
    msgs = repo.list_messages(contact_id=contact_id, limit=limit)
    updated = 0
    for m in msgs:
        if not m.content:
            continue
        intent, conf = intent_classify(m.content)
        repo.update_message_intent(m.id, intent, conf)
        updated += 1
    # 更新联系人最近意图
    if msgs:
        last = max(msgs, key=lambda x: x.created_ts)
        intent, conf = intent_classify(last.content) if last.content else ("", 0)
        repo.update_contact_intent(contact_id, intent, ts=last.created_ts)
    return {"updated": updated}


# ============================================================================
# 待办
# ============================================================================
@router.get("/todos", response_model=schemas.TodoListResponse)
def list_todos(
    status: str | None = None,
    contact_id: int | None = None,
    order_by: str = "due_ts",
) -> schemas.TodoListResponse:
    repo = get_repo()
    todos = repo.list_todos(status=status, contact_id=contact_id, order_by=order_by)
    return schemas.TodoListResponse(
        todos=[_todo_to_out(t) for t in todos],
        total=len(todos),
    )


@router.post("/todos", response_model=schemas.TodoOut)
def create_todo(req: schemas.TodoCreateRequest) -> schemas.TodoOut:
    manager = TodoManager(get_repo())
    todo_id = manager.add_manual(
        title=req.title,
        contact_id=req.contact_id,
        detail=req.detail,
        due_ts=req.due_ts,
        priority=req.priority,
    )
    repo = get_repo()
    todos = repo.list_todos()
    for t in todos:
        if t.id == todo_id:
            return _todo_to_out(t)
    raise HTTPException(500, "待办创建后未找到")


@router.patch("/todos/{todo_id}", response_model=schemas.OkResponse)
def update_todo(todo_id: int, req: schemas.TodoUpdateRequest) -> schemas.OkResponse:
    manager = TodoManager(get_repo())
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if not fields:
        return schemas.OkResponse(message="无更新字段")
    if "status" in fields:
        manager.mark_status(todo_id, fields["status"])
        fields.pop("status")
    if fields:
        manager.update(todo_id, fields)
    return schemas.OkResponse(message="已更新")


@router.delete("/todos/{todo_id}", response_model=schemas.OkResponse)
def delete_todo(todo_id: int) -> schemas.OkResponse:
    manager = TodoManager(get_repo())
    manager.delete(todo_id)
    return schemas.OkResponse(message="已删除")


@router.get("/todos/summary", response_model=schemas.TodoSummaryResponse)
def todo_summary() -> schemas.TodoSummaryResponse:
    repo = get_repo()
    by_status = repo.todo_summary()
    # 按客户汇总
    todos = repo.list_todos()
    by_contact_map: dict[int, dict[str, int]] = {}
    for t in todos:
        cid = t.contact_id or 0
        if cid not in by_contact_map:
            by_contact_map[cid] = {"pending": 0, "doing": 0, "done": 0, "cancelled": 0}
        by_contact_map[cid][t.status] = by_contact_map[cid].get(t.status, 0) + 1
    by_contact = []
    for cid, counts in by_contact_map.items():
        contact = repo.get_contact(cid) if cid else None
        name = (contact.remark or contact.nickname if contact else "通用") or "通用"
        by_contact.append({"contact_id": cid, "contact_name": name, **counts})
    return schemas.TodoSummaryResponse(by_status=by_status, by_contact=by_contact)


@router.post("/todos/auto-extract")
def auto_extract_todos(contact_id: int | None = None, limit: int = 500) -> dict:
    """从消息中自动提取待办。"""
    repo = get_repo()
    manager = TodoManager(repo)
    msgs = repo.list_messages(contact_id=contact_id, limit=limit)
    new_todos = manager.extract_and_save(msgs)
    return {"extracted": len(new_todos), "todos": [_todo_to_out(t).model_dump() for t in new_todos]}


# ============================================================================
# 智能助手（MCP）
# ============================================================================
@router.post("/assistant/query", response_model=schemas.AssistantMessageOut)
def assistant_query(req: schemas.AssistantQueryRequest) -> schemas.AssistantMessageOut:
    """自然语言查询主入口。"""
    repo = get_repo()
    parser = _get_parser()
    query = parser.parse(req.text)
    responder = _get_responder()
    result = responder.answer(query)

    # 持久化对话历史
    parsed_text = query_filter_to_text(query)
    msg_ids_str = matched_ids_str([m.id for m in result.messages if m.id is not None])

    user_turn = AssistantTurn(role="user", content=req.text, engine="local")
    repo.insert_assistant_turn(user_turn)
    assistant_turn = AssistantTurn(
        role="assistant",
        content=result.summary,
        parsed_query=parsed_text,
        matched_msg_ids=msg_ids_str,
        latency_ms=result.latency_ms,
        engine=result.engine,
    )
    turn_id = repo.insert_assistant_turn(assistant_turn)

    return schemas.AssistantMessageOut(
        id=turn_id,
        role="assistant",
        content=result.summary,
        parsed_query=parsed_text,
        matched_msg_ids=msg_ids_str,
        latency_ms=result.latency_ms,
        engine=result.engine,
        messages=[_message_to_out(m) for m in result.messages],
        contacts=[_contact_to_out(c) for c in result.contacts],
        todos=[_todo_to_out(t) for t in result.todos],
    )


@router.get("/assistant/history", response_model=schemas.AssistantHistoryResponse)
def assistant_history(limit: int = 50) -> schemas.AssistantHistoryResponse:
    repo = get_repo()
    turns = repo.list_assistant_turns(limit=limit)
    return schemas.AssistantHistoryResponse(
        turns=[
            schemas.AssistantMessageOut(
                id=t.id,
                role=t.role,
                content=t.content,
                parsed_query=t.parsed_query,
                matched_msg_ids=t.matched_msg_ids,
                latency_ms=t.latency_ms,
                engine=t.engine,
                created_ts=t.created_ts,
            )
            for t in turns
        ]
    )


# ============================================================================
# 语音转录
# ============================================================================
@router.post("/stt/transcribe-pending")
def transcribe_pending_voice(limit: int = 20) -> dict:
    """批量转录本地库中未转录的语音消息。"""
    repo = get_repo()
    engine = get_default_stt_engine()
    msgs = repo.list_untranscribed_voice_messages(limit=limit)
    results = []
    success = 0
    for m in msgs:
        try:
            if not m.raw_path:
                results.append({"id": m.id, "ok": False, "error": "无原始语音路径"})
                continue
            from pathlib import Path

            from ..stt import transcribe_voice_message

            text = transcribe_voice_message(Path(m.raw_path), engine=engine)
            repo.update_message_transcription(m.id, text)
            results.append({"id": m.id, "ok": True, "text": text[:200]})
            success += 1
        except Exception as e:  # noqa: BLE001
            results.append({"id": m.id, "ok": False, "error": str(e)[:200]})
    return {"total": len(msgs), "success": success, "results": results}


@router.get("/stt/status")
def stt_status() -> dict:
    engine = get_default_stt_engine()
    return {
        "available": engine.is_available(),
        "whisper_bin": str(engine.whisper_bin),
        "model_path": str(engine.model_path),
        "language": engine.language,
    }


# ============================================================================
# 设置
# ============================================================================
@router.get("/settings", response_model=schemas.SettingsResponse)
def get_settings() -> schemas.SettingsResponse:
    repo = get_repo()
    settings = repo.get_all_settings()

    version_info = detect_installed_wechat()
    whisper_engine = get_default_stt_engine()

    return schemas.SettingsResponse(
        wechat_version=version_info.raw_version if version_info else "",
        wechat_generation=version_info.generation.value if version_info else "",
        wechat_data_dirs=[str(p) for p in find_wechat_data_dirs(version_info)] if version_info else [],
        needs_resign=needs_resign(),
        is_resigned=is_resigned(),
        realtime_listen=settings.get("realtime_listen", "0") == "1",
        llm_api_base=settings.get("llm_api_base", ""),
        llm_model=settings.get("llm_model", ""),
        llm_api_key_set=bool(settings.get("llm_api_key", "")),
        whisper_available=whisper_engine.is_available(),
        intent_model_available=False,  # 暂未启用本地 Intento 模型
        db_path=str(get_app_data_dir() / "local.db"),
        data_dir=str(get_app_data_dir()),
    )


@router.post("/settings/llm", response_model=schemas.OkResponse)
def set_llm_config(req: schemas.LLMConfigRequest) -> schemas.OkResponse:
    repo = get_repo()
    repo.set_setting("llm_api_base", req.api_base)
    repo.set_setting("llm_api_key", req.api_key)
    repo.set_setting("llm_model", req.model)
    repo.set_setting("llm_timeout", str(req.timeout))
    return schemas.OkResponse(message="LLM 配置已保存")


@router.delete("/settings/llm", response_model=schemas.OkResponse)
def clear_llm_config() -> schemas.OkResponse:
    repo = get_repo()
    for k in ("llm_api_base", "llm_api_key", "llm_model", "llm_timeout"):
        repo.set_setting(k, "")
    return schemas.OkResponse(message="LLM 配置已清除")


@router.post("/settings/realtime", response_model=schemas.OkResponse)
def set_realtime_listen(req: schemas.RealtimeListenRequest) -> schemas.OkResponse:
    repo = get_repo()
    repo.set_setting("realtime_listen", "1" if req.enabled else "0")
    # 实际启停监听器由 main.py 的应用单例管理（此处仅持久化设置）
    return schemas.OkResponse(message=f"实时解析已{'开启' if req.enabled else '关闭'}")


@router.post("/settings/manual-key", response_model=schemas.OkResponse)
def set_manual_key(req: schemas.ManualKeyRequest) -> schemas.OkResponse:
    if not validate_manual_key(req.key_hex):
        raise HTTPException(400, "密钥格式错误，应为 64 位 hex 字符串")
    repo = get_repo()
    repo.set_setting("manual_key_hex", req.key_hex.strip().lower())
    return schemas.OkResponse(message="密钥已保存")


# ============================================================================
# 解密 / 导入
# ============================================================================
@router.get("/decrypt/status", response_model=schemas.DecryptStatusResponse)
def decrypt_status() -> schemas.DecryptStatusResponse:
    version_info = detect_installed_wechat()
    repo = get_repo()
    runs = repo.list_decrypt_runs(limit=1)
    last_run = runs[0] if runs else None
    return schemas.DecryptStatusResponse(
        wechat_detected=version_info is not None,
        wechat_version=version_info.raw_version if version_info else "",
        wechat_generation=version_info.generation.value if version_info else "",
        needs_resign=needs_resign(),
        needs_admin=False,  # Windows 上需要管理员，前端按平台判断
        data_dirs=[str(p) for p in find_wechat_data_dirs(version_info)] if version_info else [],
        last_decrypt_run=last_run,
    )


@router.post("/decrypt/trigger", response_model=schemas.DecryptTriggerResponse)
def decrypt_trigger(req: schemas.DecryptTriggerRequest) -> schemas.DecryptTriggerResponse:
    """触发一次完整的解密导入。"""
    repo = get_repo()
    version_info = detect_installed_wechat()
    if version_info is None:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未检测到本机微信，请先安装并登录微信",
        )

    started_ts = int(time.time())
    try:
        key = extract_key(
            version_info,
            source=req.source,
            manual_key=req.manual_key,
        )
    except KeyExtractionError as e:
        return schemas.DecryptTriggerResponse(ok=False, message=f"密钥提取失败：{e}")

    data_dirs = find_wechat_data_dirs(version_info)
    if not data_dirs:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未找到微信数据目录，请确认微信已登录",
        )
    data_dir = data_dirs[0]
    if req.wxid:
        data_dir = data_dir / req.wxid if hasattr(data_dir, "__truediv__") else data_dir

    msg_db = find_msg_db(version_info, data_dir)
    micro_db = find_micro_msg_db(version_info, data_dir)

    if msg_db is None and micro_db is None:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未找到微信数据库文件",
        )

    contact_count = 0
    msg_count = 0

    # 1. 联系人
    if micro_db is not None:
        try:
            conn = open_decrypted_db(micro_db, key.key_bytes, version_info.sqlcipher_compatibility)
            try:
                wxid_to_id: dict[str, int] = {}
                for parsed in iter_contacts(conn, version_info):
                    contact = to_contact_model(parsed)
                    cid = repo.upsert_contact(contact)
                    wxid_to_id[parsed.wxid] = cid
                    contact_count += 1
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            return schemas.DecryptTriggerResponse(
                ok=False,
                message=f"联系人库解密失败：{e}",
            )

    # 2. 消息
    if msg_db is not None:
        try:
            conn = open_decrypted_db(msg_db, key.key_bytes, version_info.sqlcipher_compatibility)
            try:
                # 先建立 wxid → contact_id 映射
                wxid_to_id = {c.wxid: c.id for c in repo.list_contacts() if c.id}
                msgs_to_insert: List[Message] = []
                for parsed in iter_messages(conn, version_info):
                    cid = wxid_to_id.get(parsed.talker_wxid)
                    if cid is None:
                        continue
                    msgs_to_insert.append(to_message_model(parsed, cid))
                    if len(msgs_to_insert) >= 1000:
                        repo.insert_messages_bulk(msgs_to_insert)
                        msg_count += len(msgs_to_insert)
                        msgs_to_insert = []
                if msgs_to_insert:
                    repo.insert_messages_bulk(msgs_to_insert)
                    msg_count += len(msgs_to_insert)
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            return schemas.DecryptTriggerResponse(
                ok=False,
                message=f"消息库解密失败：{e}",
            )

    finished_ts = int(time.time())
    repo.record_decrypt_run(
        wechat_version=version_info.raw_version,
        db_path=str(msg_db or micro_db),
        key_source=key.source,
        msg_count=msg_count,
        started_ts=started_ts,
        finished_ts=finished_ts,
    )

    return schemas.DecryptTriggerResponse(
        ok=True,
        message=f"解密完成：导入 {contact_count} 个联系人，{msg_count} 条消息",
        msg_count=msg_count,
        contact_count=contact_count,
    )


@router.post("/decrypt/resign", response_model=schemas.OkResponse)
def decrypt_resign(req: schemas.ResignRequest) -> schemas.OkResponse:
    result = perform_resign(password=req.password)
    if not result.success:
        raise HTTPException(400, result.message)
    return schemas.OkResponse(message=result.message)
