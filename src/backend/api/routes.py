"""FastAPI 路由：暴露所有功能给前端 Electron 调用。

所有路径以 /api 为前缀。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from ..config import get_repo, get_models_dir, get_bin_dir, get_app_data_dir
from ..decrypt import (
    KeyExtractionError,
    PollingListener,
    SSEConfig,
    WeChatGeneration,
    detect_installed_wechat,
    extract_key,
    find_all_dbs,
    find_all_msg_dbs,
    find_db_for_key,
    find_micro_msg_db,
    find_msg_db,
    find_wechat_data_dirs,
    is_resigned,
    is_sqlcipher_available,
    iter_contacts,
    iter_messages,
    needs_resign,
    open_decrypted_db,
    parse_multi_keys_json,
    perform_resign,
    to_contact_model,
    to_message_model,
    validate_manual_key,
    validate_multi_keys_json,
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
import threading as _threading

from ..stt import WhisperEngine, get_default_engine as get_default_stt_engine
from ..todo import TodoManager
from . import schemas


router = APIRouter(prefix="/api")


# ============================================================================
# 工具
# ============================================================================
def _launch_media_resolution(
    repo,
    data_dir,
    multi_keys: dict,
    version_info,
    wxid: str = "",
) -> None:
    """在后台线程中解析图片缓存文件，不阻塞解密响应。"""
    t = _threading.Thread(
        target=_resolve_images_in_background,
        args=(repo, data_dir),
        daemon=True,
        name="media-resolver",
    )
    t.start()


def _resolve_images_in_background(repo, data_dir):
    """后台扫描 cache/ 目录解密图片，更新 raw_path。"""
    import time as _time
    try:
        from ..config import get_app_data_dir
        from ..decrypt.image_decoder import decrypt_dat_image
        from pathlib import Path

        wechat_base_dir = data_dir
        if data_dir.name == "db_storage" and data_dir.parent.exists():
            wechat_base_dir = data_dir.parent

        cache_dir = wechat_base_dir / "cache"
        if not cache_dir.exists():
            return

        assets_dir = get_app_data_dir() / "assets"
        out_dir = assets_dir / "images"
        out_dir.mkdir(parents=True, exist_ok=True)

        # 单次扫描 cache 目录，解密所有 .dat 文件
        resolved = 0
        for dat_path in cache_dir.rglob("*_b.dat"):
            if dat_path.stat().st_size < 100:
                continue
            out_path = out_dir / f"{dat_path.stem}.jpg"
            if out_path.exists():
                continue
            try:
                decrypt_dat_image(dat_path, out_path)
                resolved += 1
            except Exception:
                continue

        if resolved:
            repo.set_setting("media_resolved_ts", str(int(_time.time())))
    except Exception:
        pass


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
def list_contacts(
    intent: str | None = None,
    limit: int = 200,
    offset: int = 0,
    q: str = "",
) -> schemas.ContactListResponse:
    """客户列表（支持分页和关键字搜索）。

    - limit/offset: 分页，默认每次 200 条
    - q: 按昵称/备注/wxid 搜索
    - intent: 按意向筛选
    """
    repo = get_repo()
    if q:
        contacts = repo.find_contacts_by_keyword(q)
    else:
        contacts = repo.list_contacts(intent=intent, limit=limit, offset=offset)
    total = repo.count_contacts(intent=intent) if not q else len(contacts)
    return schemas.ContactListResponse(
        contacts=[_contact_to_out(c) for c in contacts],
        total=total,
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
        llm_error=result.llm_error,
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
        sqlcipher_available=is_sqlcipher_available(),
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


@router.post("/llm/test", response_model=schemas.LLMTestResult)
def test_llm(req: schemas.LLMConfigRequest) -> schemas.LLMTestResult:
    """测试 LLM 连通性，返回详细诊断信息。

    接收完整的 LLM 配置（无需先保存即可测试），执行：
    1. 配置校验：api_base 清理反引号、检测 /v1 后缀缺失
    2. 实际调用：发送一条简短消息验证连通性
    """
    config = CloudLLMConfig(req.api_base, req.api_key, req.model, req.timeout)

    # 1. 配置校验
    hint = config.validate()
    if hint:
        return schemas.LLMTestResult(
            ok=False,
            provider="",
            config_hint=hint,
            error=f"配置问题：{hint}",
        )

    # 2. 实际调用测试（发一条简短消息）
    import httpx
    url = f"{config.api_base}/chat/completions"
    try:
        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model,
                    "messages": [{"role": "user", "content": "请回复 ok"}],
                    "temperature": 0,
                    "max_tokens": 10,
                },
            )
        if resp.status_code >= 400:
            body = resp.text[:500] if resp.text else ""
            from ..mcp.responder import _diagnose_http_error
            diag = _diagnose_http_error(resp.status_code, body, url, "")
            return schemas.LLMTestResult(
                ok=False,
                model=config.model,
                api_base=config.api_base,
                error=diag,
            )
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return schemas.LLMTestResult(
            ok=True,
            model=config.model,
            api_base=config.api_base,
            response=content[:200],
        )
    except httpx.ConnectError as e:
        return schemas.LLMTestResult(
            ok=False,
            model=config.model,
            api_base=config.api_base,
            error=f"网络连接失败：{e}。请检查 api_base 是否可访问、网络是否需要代理。URL: {url}",
        )
    except httpx.TimeoutException:
        return schemas.LLMTestResult(
            ok=False,
            model=config.model,
            api_base=config.api_base,
            error=f"调用超时（{config.timeout}s）。URL: {url}",
        )
    except Exception as e:  # noqa: BLE001
        return schemas.LLMTestResult(
            ok=False,
            model=config.model,
            api_base=config.api_base,
            error=f"{type(e).__name__}: {e}",
        )


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


@router.post("/settings/manual-keys-json", response_model=schemas.OkResponse)
def set_manual_keys_json(req: schemas.ManualKeysJsonRequest) -> schemas.OkResponse:
    """保存微信 4.0.x 多数据库密钥 JSON。"""
    if not validate_multi_keys_json(req.keys_json):
        raise HTTPException(400, "多密钥 JSON 格式错误，应为 {db_path: {enc_key: hex64}} 结构")
    repo = get_repo()
    repo.set_setting("manual_keys_json", req.keys_json.strip())
    return schemas.OkResponse(message=f"多密钥 JSON 已保存（{len(parse_multi_keys_json(req.keys_json))} 个数据库）")


@router.get("/settings/manual-keys-json", response_model=dict)
def get_manual_keys_json() -> dict:
    """读取已保存的多密钥 JSON。"""
    repo = get_repo()
    raw = repo.get_setting("manual_keys_json", "")
    return {"keys_json": raw, "has_keys": bool(raw)}


@router.post("/settings/data-dir", response_model=schemas.OkResponse)
def set_manual_data_dir(req: dict) -> schemas.OkResponse:
    """保存手动指定的微信数据目录。"""
    data_dir = (req.get("data_dir") or "").strip()
    repo = get_repo()
    if data_dir:
        from pathlib import Path

        p = Path(data_dir).expanduser()
        if not p.exists():
            raise HTTPException(400, f"目录不存在：{data_dir}")
        repo.set_setting("manual_data_dir", str(p.resolve()))
    else:
        repo.set_setting("manual_data_dir", "")
    return schemas.OkResponse(message="数据目录已保存")


@router.get("/settings/data-dir", response_model=dict)
def get_manual_data_dir() -> dict:
    """读取手动指定的微信数据目录。"""
    repo = get_repo()
    raw = repo.get_setting("manual_data_dir", "")
    return {"data_dir": raw, "has_dir": bool(raw)}


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


@router.post("/decrypt/incremental", response_model=schemas.IncrementalDecryptResponse)
def decrypt_incremental() -> schemas.IncrementalDecryptResponse:
    """手动触发一次增量同步：只拉取本地库中最新消息之后的新消息。

    与 `/decrypt/trigger` 的区别：
    - 不重新解密联系人库、不重跑全量消息导入
    - 仅扫描消息库中 created_ts > 本地最大 created_ts 的消息
    - 适合在实时监听未开启时，用户手动点一下拉取增量

    返回新增消息数、使用的数据库路径等信息。
    """
    # 延迟导入避免循环依赖：main 模块在 import 时会构造 app 实例
    from ..main import incremental_sync_once

    result = incremental_sync_once()
    return schemas.IncrementalDecryptResponse(
        ok=bool(result.get("ok", False)),
        message=result.get("message", ""),
        new_msg_count=int(result.get("new_msg_count", 0)),
        data_dir=result.get("data_dir", ""),
        db_path=result.get("db_path", ""),
    )


@router.post("/decrypt/trigger", response_model=schemas.DecryptTriggerResponse)
def decrypt_trigger(req: schemas.DecryptTriggerRequest) -> schemas.DecryptTriggerResponse:
    """触发一次完整的解密导入。

    支持两种模式：
    1. 单密钥（source=manual, manual_key=hex64）：适用于 3.x 或用户提供单一 key
    2. 多密钥 JSON（source=multi_keys, manual_keys_json=json）：适用于 4.0.x 多数据库
    3. 自动提取（source=auto）：从内存/注册表提取（需要相应权限）
    """
    repo = get_repo()
    version_info = detect_installed_wechat()

    # 若未检测到版本，但有手动密钥，构造一个默认 4.0 版本信息（用户可能从其他工具拿到 key）
    if version_info is None:
        if req.manual_keys_json or (req.source == "multi_keys"):
            from ..decrypt.adapter import WeChatGeneration, WeChatVersionInfo, Platform, _detect_platform
            version_info = WeChatVersionInfo(
                raw_version="4.0.0.0",
                major=4, minor=0, patch=0, build=0,
                generation=WeChatGeneration.GEN_4,
                platform=_detect_platform(),
                sqlcipher_compatibility=4,
            )
        elif req.manual_key:
            from ..decrypt.adapter import WeChatGeneration, WeChatVersionInfo, _detect_platform
            version_info = WeChatVersionInfo(
                raw_version="4.0.0.0",
                major=4, minor=0, patch=0, build=0,
                generation=WeChatGeneration.GEN_4,
                platform=_detect_platform(),
                sqlcipher_compatibility=4,
            )
        else:
            return schemas.DecryptTriggerResponse(
                ok=False,
                message="未检测到本机微信。请先安装并登录微信，或提供手动密钥/多密钥 JSON。",
            )

    # 检测 SQLCipher 可用性
    if not is_sqlcipher_available():
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未安装 pysqlcipher3 且系统无 sqlcipher 命令，无法解密。请安装 pysqlcipher3 或 sqlcipher。",
        )

    started_ts = int(time.time())
    data_dirs = find_wechat_data_dirs(version_info)

    # 手动指定数据目录（优先级：请求参数 > 已保存设置 > 自动检测）
    manual_dir = (req.data_dir or "").strip() or repo.get_setting("manual_data_dir", "")
    if manual_dir:
        from pathlib import Path

        manual_path = Path(manual_dir).expanduser()
        if manual_path.exists():
            # 手动指定的目录优先于自动检测
            data_dirs = [manual_path] + data_dirs

    # ---- 多密钥 JSON 模式（4.0.x） ----
    multi_keys_raw = req.manual_keys_json
    if not multi_keys_raw and req.source != "multi_keys":
        # 也尝试从 settings 读取之前保存的多密钥 JSON
        multi_keys_raw = repo.get_setting("manual_keys_json", "")

    if multi_keys_raw and (req.source in ("multi_keys", "auto", "manual") or req.manual_keys_json):
        return _decrypt_with_multi_keys(
            repo, version_info, data_dirs, multi_keys_raw, started_ts, req.wxid
        )

    # ---- 单密钥模式 ----
    try:
        if req.source == "manual" and req.manual_key:
            from ..decrypt import make_manual_key
            key = make_manual_key(req.manual_key)
        elif req.source == "auto" and repo.get_setting("manual_key_hex", ""):
            from ..decrypt import make_manual_key
            key = make_manual_key(repo.get_setting("manual_key_hex", ""))
        else:
            key = extract_key(
                version_info,
                source=req.source,
                manual_key=req.manual_key,
            )
    except KeyExtractionError as e:
        return schemas.DecryptTriggerResponse(ok=False, message=f"密钥提取失败：{e}")

    if not data_dirs:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未找到微信数据目录，请确认微信已登录",
        )
    data_dir = data_dirs[0]

    msg_db = find_msg_db(version_info, data_dir)
    micro_db = find_micro_msg_db(version_info, data_dir)

    if msg_db is None and micro_db is None:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未找到微信数据库文件",
        )

    db_results: List[schemas.DecryptDbResult] = []
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
            db_results.append(schemas.DecryptDbResult(
                db_path=str(micro_db), ok=True, message="联系人导入完成", contact_count=contact_count
            ))
        except Exception as e:  # noqa: BLE001
            db_results.append(schemas.DecryptDbResult(
                db_path=str(micro_db), ok=False, message=f"联系人库解密失败：{e}"
            ))

    # 2. 消息
    if msg_db is not None:
        try:
            conn = open_decrypted_db(msg_db, key.key_bytes, version_info.sqlcipher_compatibility)
            try:
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
            db_results.append(schemas.DecryptDbResult(
                db_path=str(msg_db), ok=True, message="消息导入完成", msg_count=msg_count
            ))
        except Exception as e:  # noqa: BLE001
            db_results.append(schemas.DecryptDbResult(
                db_path=str(msg_db), ok=False, message=f"消息库解密失败：{e}"
            ))

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
        db_results=db_results,
    )


def _decrypt_with_multi_keys(
    repo,
    version_info,
    data_dirs: list,
    keys_json_raw: str,
    started_ts: int,
    wxid: Optional[str],
) -> schemas.DecryptTriggerResponse:
    """使用多密钥 JSON 解密微信 4.0.x 的多个数据库。

    用户的 JSON 格式：
        {
          "message/message_0.db": {"enc_key": "..."},
          "contact/contact.db": {"enc_key": "..."},
          ...
        }
    """
    try:
        multi_keys = parse_multi_keys_json(keys_json_raw)
    except KeyExtractionError as e:
        return schemas.DecryptTriggerResponse(ok=False, message=str(e))

    if not multi_keys:
        return schemas.DecryptTriggerResponse(ok=False, message="多密钥 JSON 为空")

    if not data_dirs:
        return schemas.DecryptTriggerResponse(
            ok=False,
            message="未找到微信数据目录，请确认微信已登录或手动指定数据目录",
        )

    # 收集所有候选数据目录的 .db 文件索引。
    # 注意：find_wechat_data_dirs 可能返回父目录（如 base_3x 容器根）和账号根目录。
    # 父目录会 rglob 出多个账号的 .db，相对路径不匹配 JSON key，因此：
    # - 优先在「账号根目录」（直接含 message/ 或 Msg/）中查找
    # - 对每个 JSON key，依次在所有账号目录中查找，找到即用
    from pathlib import Path

    def _is_account_root(d: Path) -> bool:
        """判断目录是否为账号根目录（直接含 message/ 或 Msg/ 子目录）。

        macOS 大小写不敏感文件系统上，message 和 Message 可能是同一目录，
        但目录名保留创建时的大小写，因此同时检查大小写两种形式。
        """
        for name in ("message", "Message", "Msg", "MSG"):
            if (d / name).is_dir():
                return True
        return False

    def _is_4x_account_root(d: Path) -> bool:
        """判断是否为 4.x 账号根目录：含小写 message/ 且其中有 message_*.db。"""
        msg_dir = d / "message"
        if msg_dir.is_dir():
            return any(msg_dir.glob("message_*.db"))
        return False

    def _scan_dbs(d: Path) -> dict:
        try:
            return find_all_dbs(version_info, d)
        except Exception:
            return {}

    # 按优先级收集所有候选目录的 db 索引：4.x 账号根目录优先，3.x 账号根目录其次，父目录兜底
    gen4_account_dirs: list[tuple[Path, dict]] = []
    gen3_account_dirs: list[tuple[Path, dict]] = []
    parent_dirs: list[tuple[Path, dict]] = []
    for d in data_dirs:
        dbs = _scan_dbs(d)
        if not dbs:
            continue
        if _is_4x_account_root(d):
            gen4_account_dirs.append((d, dbs))
        elif _is_account_root(d) and version_info.generation == WeChatGeneration.GEN_4:
            # 在 4.x 检测环境下的非 4.x 账号根目录（如 3.x 遗留目录），放最后
            gen3_account_dirs.append((d, dbs))
        elif _is_account_root(d):
            gen3_account_dirs.append((d, dbs))
        else:
            parent_dirs.append((d, dbs))

    # 排序：4.x 账号目录优先，按 wxid 匹配 + db 数量降序
    def _dir_sort_key(item: tuple[Path, dict]) -> tuple:
        d, dbs = item
        wxid_match = 1 if (wxid and (d.name == wxid or wxid in str(d))) else 0
        return (-wxid_match, -len(dbs))

    gen4_account_dirs.sort(key=_dir_sort_key)
    gen3_account_dirs.sort(key=_dir_sort_key)
    # 4.x 环境只含 4.x 目录；含遗留 3.x 目录仅作兜底
    all_search_dirs = gen4_account_dirs + gen3_account_dirs + parent_dirs

    if not all_search_dirs:
        tried_paths = "; ".join(str(d) for d in data_dirs[:5])
        return schemas.DecryptTriggerResponse(
            ok=False,
            message=(
                f"在 {len(data_dirs)} 个候选数据目录下均未找到 .db 文件。"
                f"已尝试：{tried_paths}。"
                "请在设置页『微信数据目录（手动指定）』填入正确的账号目录绝对路径"
                "（应包含 message/、contact/ 等子目录）。"
            ),
        )

    # 主数据目录（用于诊断信息展示）
    data_dir = all_search_dirs[0][0]
    all_dbs = all_search_dirs[0][1]

    def _find_db_anywhere(rel_path: str) -> Optional[Path]:
        """在所有候选数据目录中查找 db 文件，返回第一个匹配的绝对路径。"""
        for _d, dbs in all_search_dirs:
            p = find_db_for_key(dbs, rel_path)
            if p and p.exists():
                return p
        return None

    db_results: List[schemas.DecryptDbResult] = []
    total_msg_count = 0
    total_contact_count = 0

    # wxid → contact_id 映射，跨库复用
    wxid_to_id: dict[str, int] = {c.wxid: c.id for c in repo.list_contacts() if c.id}

    def _not_found_msg(rel_path: str) -> str:
        """构造「数据库文件未找到」的诊断信息：显示全部 .db 文件 + basename 模糊匹配。"""
        basename = rel_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        parts = []
        for d, dbs in all_search_dirs:
            all_files = list(dbs.keys())
            fuzzy = [k for k in all_files if k.replace("\\", "/").rsplit("/", 1)[-1].lower() == basename]
            parts.append(
                f"目录 {d}（{len(all_files)} 个 .db）：{all_files}；"
                f"按文件名 '{basename}' 模糊匹配：{fuzzy or '无'}"
            )
        return "数据库文件未找到。" + " | ".join(parts)

    # 先解密联系人库（跳过 FTS 索引库，它们常有独立密钥且非业务必需）
    contact_db_keys = {k: v for k, v in multi_keys.items()
                       if "contact" in k.lower() and "fts" not in k.lower()}
    for rel_path, key_entry in contact_db_keys.items():
        db_path = _find_db_anywhere(rel_path)
        if db_path is None or not db_path.exists():
            db_results.append(schemas.DecryptDbResult(
                db_path=rel_path, ok=False, message=_not_found_msg(rel_path),
            ))
            continue
        try:
            conn = open_decrypted_db(db_path, key_entry.key_bytes, version_info.sqlcipher_compatibility)
            try:
                count = 0
                for parsed in iter_contacts(conn, version_info):
                    contact = to_contact_model(parsed)
                    cid = repo.upsert_contact(contact)
                    wxid_to_id[parsed.wxid] = cid
                    count += 1
                total_contact_count += count
                db_results.append(schemas.DecryptDbResult(
                    db_path=str(db_path), ok=True, message=f"导入 {count} 个联系人", contact_count=count
                ))
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            err_msg = str(e)
            if "file is not a database" in err_msg or "not a database" in err_msg:
                err_msg = f"密钥不匹配或数据库损坏（sqlcipher 报 file is not a database）。该库的 enc_key 可能不正确。原始错误：{err_msg}"
            db_results.append(schemas.DecryptDbResult(
                db_path=str(db_path), ok=False, message=f"解密失败：{err_msg}"
            ))

    # 再解密消息库（所有 message_*.db，跳过 FTS 和 biz 索引库）
    msg_db_keys = {k: v for k, v in multi_keys.items() if "message" in k.lower() and "fts" not in k.lower() and "biz" not in k.lower()}
    for rel_path, key_entry in msg_db_keys.items():
        db_path = _find_db_anywhere(rel_path)
        if db_path is None or not db_path.exists():
            db_results.append(schemas.DecryptDbResult(
                db_path=rel_path, ok=False, message=_not_found_msg(rel_path),
            ))
            continue
        try:
            conn = open_decrypted_db(db_path, key_entry.key_bytes, version_info.sqlcipher_compatibility)
            try:
                msgs_to_insert: List[Message] = []
                db_msg_count = 0
                # 微信 4.x 使用 Msg_<md5(username)> 频道表，需要 self_wxid 判断 is_self
                self_wxid = wxid or ""
                for parsed in iter_messages(conn, version_info, self_wxid=self_wxid):
                    cid = wxid_to_id.get(parsed.talker_wxid)
                    if cid is None:
                        # 联系人不存在时也创建占位联系人
                        from ..storage.models import Contact
                        cid = repo.upsert_contact(Contact(wxid=parsed.talker_wxid))
                        wxid_to_id[parsed.talker_wxid] = cid
                    msgs_to_insert.append(to_message_model(parsed, cid))
                    if len(msgs_to_insert) >= 1000:
                        repo.insert_messages_bulk(msgs_to_insert)
                        db_msg_count += len(msgs_to_insert)
                        msgs_to_insert = []
                if msgs_to_insert:
                    repo.insert_messages_bulk(msgs_to_insert)
                    db_msg_count += len(msgs_to_insert)
                total_msg_count += db_msg_count
                db_results.append(schemas.DecryptDbResult(
                    db_path=str(db_path), ok=True, message=f"导入 {db_msg_count} 条消息", msg_count=db_msg_count
                ))
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            err_msg = str(e)
            if "file is not a database" in err_msg or "not a database" in err_msg:
                err_msg = f"密钥不匹配或数据库损坏。原始错误：{err_msg}"
            db_results.append(schemas.DecryptDbResult(
                db_path=str(db_path), ok=False, message=f"解密失败：{err_msg}"
            ))

    # ---- 记录解密完成 ----
    finished_ts = int(time.time())
    repo.record_decrypt_run(
        wechat_version=version_info.raw_version,
        db_path=str(data_dir),
        key_source="multi_keys",
        msg_count=total_msg_count,
        started_ts=started_ts,
        finished_ts=finished_ts,
    )

    # ---- 在后台启动媒体文件解析（不阻塞解密流程）----
    if total_msg_count > 0:
        _launch_media_resolution(repo, data_dir, multi_keys, version_info, wxid)

    success_count = sum(1 for r in db_results if r.ok)
    result_msg = (
        f"解密完成：{success_count}/{len(db_results)} 个数据库成功，"
        f"导入 {total_contact_count} 个联系人，{total_msg_count} 条消息"
    )

    return schemas.DecryptTriggerResponse(
        ok=success_count > 0,
        message=result_msg,
        msg_count=total_msg_count,
        contact_count=total_contact_count,
        db_results=db_results,
    )


@router.post("/decrypt/resign", response_model=schemas.OkResponse)
def decrypt_resign(req: schemas.ResignRequest) -> schemas.OkResponse:
    result = perform_resign(password=req.password)
    if not result.success:
        raise HTTPException(400, result.message)
    return schemas.OkResponse(message=result.message)
