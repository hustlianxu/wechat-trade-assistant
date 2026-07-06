"""FastAPI 后端：提供联系人/消息/语音转录/LLM/意图/待办 API。

启动方式：
    cd wechat-ui/backend
    python main.py
    # 或 uvicorn main:app --host 0.0.0.0 --port 8766

前端默认连接 http://localhost:8766
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 同时支持「python -m backend.main」（包模式）和「cd backend && python main.py」（脚本模式）
try:
    from .config import load_config, save_config, update_config, default_config
    from .db_reader import DbReader, Contact, Message, split_msg_type, msg_type_name
    from .voice import transcribe_voice, silk_to_wav
    from .llm import (
        LLMClient, get_active_llm,
        classify_intent, extract_todos, summarize_conversation,
        classify_intent_rules,
    )
    from .auto_setup import run_auto_setup, auto_detect_decrypted_dir, try_auto_decrypt
except ImportError:
    from config import load_config, save_config, update_config, default_config
    from db_reader import DbReader, Contact, Message, split_msg_type, msg_type_name
    from voice import transcribe_voice, silk_to_wav
    from llm import (
        LLMClient, get_active_llm,
        classify_intent, extract_todos, summarize_conversation,
        classify_intent_rules,
    )
    from auto_setup import run_auto_setup, auto_detect_decrypted_dir, try_auto_decrypt


# ============================================================================
# 启动时自动检测配置（傻瓜式）
# ============================================================================
def _ensure_config_on_startup():
    """启动时检查配置，若不完整则自动检测并补全。

    只在 decrypted_dir 缺失或路径无效时触发，避免覆盖用户手动配置。
    """
    cfg = load_config()
    decrypted_dir = cfg.get("decrypted_dir", "")
    needs_setup = (
        not decrypted_dir
        or not Path(decrypted_dir).exists()
        or not cfg.get("self_wxid", "")
    )
    if not needs_setup:
        return

    print("[startup] 配置不完整，开始自动检测...", file=__import__("sys").stderr)
    try:
        result = run_auto_setup()
        updates = {}
        if result.get("decrypted_dir") and (
            not decrypted_dir or not Path(decrypted_dir).exists()
        ):
            updates["decrypted_dir"] = result["decrypted_dir"]
        if result.get("wechat_base_dir") and not cfg.get("wechat_base_dir"):
            updates["wechat_base_dir"] = result["wechat_base_dir"]
        if result.get("self_wxid") and not cfg.get("self_wxid"):
            updates["self_wxid"] = result["self_wxid"]
        if result.get("whisper") and not cfg.get("whisper", {}).get("binary_path"):
            updates["whisper"] = result["whisper"]

        if updates:
            update_config(updates)
            print(f"[startup] 自动配置完成：{list(updates.keys())}", file=__import__("sys").stderr)
            for msg in result.get("messages", []):
                print(f"[startup]   {msg}", file=__import__("sys").stderr)
            if result.get("needs_manual_action"):
                print(f"[startup] ⚠ 需手动操作：\n{result['needs_manual_action']}", file=__import__("sys").stderr)
        else:
            print("[startup] 自动检测未找到可用配置，请在设置页手动填写", file=__import__("sys").stderr)
    except Exception as e:
        print(f"[startup] 自动配置失败：{e}", file=__import__("sys").stderr)


# 模块加载时执行自动检测
_ensure_config_on_startup()


app = FastAPI(title="WeChat UI Backend", version="1.0.0")

# 允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局 DbReader 实例（按配置目录延迟初始化）
_reader: Optional[DbReader] = None
_reader_dir: str = ""


def get_reader() -> DbReader:
    """获取 DbReader 实例（配置变更时自动重建）。

    若 decrypted_dir 缺失或无效，会自动触发一次 auto_setup 尝试补全；
    仍失败则抛出 400，并附上明确的引导信息。
    """
    global _reader, _reader_dir
    cfg = load_config()
    decrypted_dir = cfg.get("decrypted_dir", "")

    # 自动补救：若路径无效，触发一次 auto_setup
    if not decrypted_dir or not Path(decrypted_dir).exists():
        try:
            result = run_auto_setup()
            if result.get("decrypted_dir"):
                update_config({"decrypted_dir": result["decrypted_dir"]})
                if result.get("self_wxid") and not cfg.get("self_wxid"):
                    update_config({"self_wxid": result["self_wxid"]})
                decrypted_dir = result["decrypted_dir"]
        except Exception:
            pass

    if not decrypted_dir:
        raise HTTPException(
            400,
            "未检测到解密目录。请确认已用 wechat-decrypt 完成解密，"
            "或在前端「设置」页点击「自动检测」按钮。"
        )
    if not Path(decrypted_dir).exists():
        raise HTTPException(
            400,
            f"解密目录不存在：{decrypted_dir}。请重新运行 wechat-decrypt 解密，"
            "或在前端「设置」页点击「自动检测」重新配置。"
        )
    if _reader is None or _reader_dir != decrypted_dir:
        _reader = DbReader(decrypted_dir)
        _reader_dir = decrypted_dir
    return _reader


# ============================================================================
# 健康检查
# ============================================================================
@app.get("/api/health")
def health():
    cfg = load_config()
    return {
        "ok": True,
        "ts": int(time.time()),
        "decrypted_dir": cfg.get("decrypted_dir", ""),
        "self_wxid": cfg.get("self_wxid", ""),
        "whisper_configured": bool(cfg.get("whisper", {}).get("binary_path")),
        "llm_configured": bool(cfg.get("active_llm")),
    }


# ============================================================================
# 配置
# ============================================================================
@app.get("/api/config")
def get_config():
    return load_config()


class ConfigUpdate(BaseModel):
    decrypted_dir: Optional[str] = None
    wechat_base_dir: Optional[str] = None
    self_wxid: Optional[str] = None
    whisper: Optional[dict] = None
    llm_providers: Optional[list] = None
    active_llm: Optional[str] = None


@app.post("/api/config")
def set_config(req: ConfigUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    # 重置 reader 缓存
    global _reader, _reader_dir
    if "decrypted_dir" in updates:
        _reader = None
        _reader_dir = ""
    return update_config(updates)


# ============================================================================
# 自动检测与自动解密（傻瓜式配置）
# ============================================================================
@app.post("/api/auto-setup")
def trigger_auto_setup(force: bool = False):
    """手动触发自动检测配置。

    流程：
    1. 检测已存在的 decrypted 目录
    2. 若不存在，尝试调用 wechat-decrypt 增量解密
    3. 自动检测微信数据目录、self_wxid、whisper.cpp
    4. 把检测到的配置写回 config.json
    """
    result = run_auto_setup(force=force)

    # 写回配置（只更新非空字段，不覆盖用户已填的 LLM 配置）
    updates = {}
    if result.get("decrypted_dir"):
        updates["decrypted_dir"] = result["decrypted_dir"]
    if result.get("wechat_base_dir"):
        updates["wechat_base_dir"] = result["wechat_base_dir"]
    if result.get("self_wxid"):
        updates["self_wxid"] = result["self_wxid"]
    if result.get("whisper"):
        updates["whisper"] = result["whisper"]

    if updates:
        update_config(updates)
        # 重置 reader 缓存
        global _reader, _reader_dir
        if "decrypted_dir" in updates:
            _reader = None
            _reader_dir = ""

    return result


@app.get("/api/auto-setup/status")
def auto_setup_status():
    """返回当前自动检测状态（不修改配置）。"""
    decrypted_dir = auto_detect_decrypted_dir()
    return {
        "has_decrypted_dir": decrypted_dir is not None,
        "decrypted_dir_preview": decrypted_dir or "",
    }


# ============================================================================
# 增量解密：只拉取本地库中最新消息之后的新消息
# ============================================================================
@app.post("/api/decrypt/incremental")
def decrypt_incremental():
    """触发增量解密。

    复用 auto_setup.try_auto_decrypt 的逻辑（调用 wechat-decrypt 的
    `decrypt_db.py -i`），只解密本地库中尚未覆盖的新消息，不重新解密
    联系人库。完成后把新的 decrypted_dir 写回配置并重置 reader 缓存。

    返回：
        {
            "ok": bool,
            "decrypted_dir": str,
            "decrypted_count": int,
            "message": str,
        }
    """
    result = try_auto_decrypt()

    if result.get("success"):
        decrypted_dir = result.get("decrypted_dir", "") or ""
        if decrypted_dir:
            update_config({"decrypted_dir": decrypted_dir})
            # 重置 reader 缓存，使其重新加载新解密的数据库
            global _reader, _reader_dir
            _reader = None
            _reader_dir = ""
        return {
            "ok": True,
            "decrypted_dir": decrypted_dir,
            "decrypted_count": result.get("decrypted_count", 0),
            "message": result.get("message", "增量解密成功"),
        }
    return {
        "ok": False,
        "decrypted_dir": "",
        "decrypted_count": 0,
        "message": result.get("message", "增量解密失败"),
    }


# ============================================================================
# 联系人 / 会话列表
# ============================================================================
@app.get("/api/contacts")
def list_contacts(
    type: str = Query("all", description="friends | groups | recent | all"),
    sort: str = Query("recent", description="recent | name"),
):
    """列出联系人/群聊/最近会话。"""
    reader = get_reader()
    cfg = load_config()
    self_wxid = cfg.get("self_wxid", "")
    contacts = reader.list_contacts(contact_type=type, sort=sort, self_wxid=self_wxid)
    return {
        "total": len(contacts),
        "contacts": [_contact_to_dict(c) for c in contacts],
    }


@app.get("/api/contacts/{username}")
def get_contact(username: str):
    """获取单个联系人详情。"""
    reader = get_reader()
    c = reader.get_contact(username)
    if c is None:
        raise HTTPException(404, "联系人不存在")
    return _contact_to_dict(c)


def _contact_to_dict(c: Contact) -> dict:
    return {
        "username": c.username,
        "nickname": c.nickname,
        "remark": c.remark,
        "alias": c.alias,
        "display_name": c.display_name,
        "is_group": c.is_group,
        "is_official": c.is_official,
        "last_msg_ts": c.last_msg_ts,
        "last_msg_summary": c.last_msg_summary,
        "last_msg_type": c.last_msg_type,
        "unread_count": c.unread_count,
    }


# ============================================================================
# 消息
# ============================================================================
@app.get("/api/messages/{username}")
def list_messages(
    username: str,
    start_ts: int = 0,
    end_ts: int = 0,
    limit: int = 500,
    offset: int = 0,
):
    """列出某个会话的消息。"""
    reader = get_reader()
    cfg = load_config()
    self_wxid = cfg.get("self_wxid", "")
    messages = reader.list_messages(
        username=username,
        self_wxid=self_wxid,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        offset=offset,
    )
    return {
        "total": len(messages),
        "messages": [_message_to_dict(m, username) for m in messages],
    }


@app.get("/api/search")
def search_messages(
    keyword: str,
    username: str = "",
    limit: int = 100,
):
    """搜索消息。"""
    reader = get_reader()
    messages = reader.search_messages(keyword=keyword, username=username, limit=limit)
    return {
        "total": len(messages),
        "messages": [_message_to_dict(m, username) for m in messages],
    }


def _message_to_dict(m: Message, chat_username: str = "") -> dict:
    base, sub = split_msg_type(m.local_type)
    # 解析 XML 内容（图片/链接/位置等）
    content = m.content
    parsed = _parse_msg_content(m.base_type, content)

    return {
        "local_id": m.local_id,
        "server_id": m.server_id,
        "local_type": m.local_type,
        "base_type": base,
        "sub_type": sub,
        "type_name": m.type_name,
        "create_time": m.create_time,
        "sender_wxid": m.sender_wxid,
        "is_self": m.is_self,
        "content": content,
        "parsed": parsed,
        "transcription": m.transcription,
    }


def _parse_msg_content(base_type: int, content: str) -> dict:
    """解析 XML 格式的消息内容（图片/链接/位置/文件等）。"""
    import xml.etree.ElementTree as ET

    if not content or not content.strip().startswith("<"):
        return {}

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}

    result = {}

    if base_type == 3:  # 图片
        img = root.find(".//img") or root
        result["md5"] = img.get("md5", "")
        result["width"] = int(img.get("width", 0))
        result["height"] = int(img.get("height", 0))

    elif base_type == 34:  # 语音
        voice = root.find(".//voicemsg") or root
        result["length"] = int(voice.get("voicelength", 0))

    elif base_type == 43:  # 视频
        video = root.find(".//videomsg")
        if video is not None:
            result["length"] = int(video.get("playlength", 0))

    elif base_type == 49:  # 链接/文件/小程序
        appmsg = root.find(".//appmsg")
        if appmsg is not None:
            result["title"] = appmsg.findtext("title", "")
            result["description"] = appmsg.findtext("des", "")
            result["url"] = appmsg.findtext("url", "")
            result["app_type"] = int(appmsg.findtext("type", "0"))
            result["type_name"] = appmsg.findtext("type", "")

    elif base_type == 48:  # 位置
        loc = root.find(".//location")
        if loc is not None:
            result["poiname"] = loc.get("poiname", "")
            result["label"] = loc.get("label", "")
            result["lat"] = float(loc.get("x", 0))
            result["lng"] = float(loc.get("y", 0))

    elif base_type == 47:  # 表情
        emoji = root.find(".//emoji")
        if emoji is not None:
            result["md5"] = emoji.get("md5", "")
            result["desc"] = emoji.get("des", "")

    return result


# ============================================================================
# 语音转录
# ============================================================================
class TranscribeRequest(BaseModel):
    username: str
    local_id: int


@app.post("/api/transcribe")
def transcribe(req: TranscribeRequest):
    """转录语音消息。"""
    reader = get_reader()
    cfg = load_config()

    # 1. 获取 SILK 语音数据
    silk_data = reader.get_voice_data(req.username, req.local_id)
    if silk_data is None:
        raise HTTPException(404, "语音数据未找到")

    # 2. 获取 LLM 配置（用于兜底）
    whisper_config = cfg.get("whisper", {})
    llm_config = None
    # 找一个支持语音转录的 LLM（OpenAI Whisper API 兼容）
    active_llm_name = cfg.get("active_llm", "")
    for p in cfg.get("llm_providers", []):
        if p.get("name") == active_llm_name and p.get("whisper_model"):
            llm_config = {
                "api_base": p.get("api_base", ""),
                "api_key": p.get("api_key", ""),
                "model": p.get("whisper_model", "whisper-1"),
            }
            break

    # 3. 转录
    text, source = transcribe_voice(silk_data, whisper_config, llm_config)
    return {"text": text, "source": source}


# ============================================================================
# 语音数据（WAV 流式播放）
# ============================================================================
@app.get("/api/voice/{username}/{local_id}")
def get_voice_wav(username: str, local_id: int):
    """获取语音的 WAV 数据（前端可直接播放）。"""
    from fastapi.responses import Response
    reader = get_reader()
    silk_data = reader.get_voice_data(username, local_id)
    if silk_data is None:
        raise HTTPException(404, "语音数据未找到")

    try:
        wav_data = silk_to_wav(silk_data)
        return Response(content=wav_data, media_type="audio/wav")
    except Exception as e:
        raise HTTPException(500, f"SILK 转 WAV 失败：{e}")


# ============================================================================
# LLM：意图识别 / 待办提取 / 会话总结
# ============================================================================
@app.post("/api/analyze/intent/{username}")
def analyze_intent(
    username: str,
    start_ts: int = 0,
    end_ts: int = 0,
    limit: int = 100,
):
    """分析会话意图。"""
    reader = get_reader()
    cfg = load_config()
    self_wxid = cfg.get("self_wxid", "")
    messages = reader.list_messages(
        username=username, self_wxid=self_wxid,
        start_ts=start_ts, end_ts=end_ts, limit=limit,
    )

    if not messages:
        return {"intent": "none", "confidence": 0, "summary": "无消息"}

    # 转换为 LLM 输入格式
    msg_list = []
    for m in messages:
        if m.is_system:
            continue
        msg_list.append({
            "sender": "自己" if m.is_self else "对方",
            "content": m.content[:500] if m.content else f"[{m.type_name}]",
            "time": datetime.fromtimestamp(m.create_time).strftime("%Y-%m-%d %H:%M") if m.create_time else "",
        })

    llm = get_active_llm(cfg)
    if llm and llm.available:
        result = classify_intent(msg_list, llm)
    else:
        # 规则兜底
        all_text = " ".join(m["content"] for m in msg_list)
        intent, conf = classify_intent_rules(all_text)
        result = {"intent": intent, "confidence": conf, "summary": "基于关键词的规则识别", "llm_error": ""}

    return result


@app.post("/api/analyze/todos/{username}")
def analyze_todos(
    username: str,
    start_ts: int = 0,
    end_ts: int = 0,
    limit: int = 100,
):
    """从会话中提取待办事项。"""
    reader = get_reader()
    cfg = load_config()
    self_wxid = cfg.get("self_wxid", "")
    messages = reader.list_messages(
        username=username, self_wxid=self_wxid,
        start_ts=start_ts, end_ts=end_ts, limit=limit,
    )

    if not messages:
        return {"todos": []}

    msg_list = []
    for m in messages:
        if m.is_system:
            continue
        msg_list.append({
            "sender": "自己" if m.is_self else "对方",
            "content": m.content[:500] if m.content else f"[{m.type_name}]",
            "time": datetime.fromtimestamp(m.create_time).strftime("%Y-%m-%d %H:%M") if m.create_time else "",
        })

    llm = get_active_llm(cfg)
    if llm and llm.available:
        todos, err = extract_todos(msg_list, llm)
        return {"todos": todos, "llm_error": err}
    return {"todos": [], "error": "未配置 LLM，无法提取待办", "llm_error": ""}


@app.post("/api/analyze/summary/{username}")
def analyze_summary(
    username: str,
    start_ts: int = 0,
    end_ts: int = 0,
    limit: int = 200,
):
    """总结会话。"""
    reader = get_reader()
    cfg = load_config()
    self_wxid = cfg.get("self_wxid", "")
    messages = reader.list_messages(
        username=username, self_wxid=self_wxid,
        start_ts=start_ts, end_ts=end_ts, limit=limit,
    )

    if not messages:
        return {"summary": "无消息"}

    msg_list = []
    for m in messages:
        if m.is_system:
            continue
        msg_list.append({
            "sender": "自己" if m.is_self else "对方",
            "content": m.content[:500] if m.content else f"[{m.type_name}]",
            "time": datetime.fromtimestamp(m.create_time).strftime("%Y-%m-%d %H:%M") if m.create_time else "",
        })

    llm = get_active_llm(cfg)
    if llm and llm.available:
        summary, err = summarize_conversation(msg_list, llm)
        return {"summary": summary, "llm_error": err}
    return {"summary": "未配置 LLM，无法生成总结", "llm_error": ""}


# ============================================================================
# LLM 连通性测试
# ============================================================================
class LLMTestRequest(BaseModel):
    """LLM 测试请求：接收完整的 provider 配置，无需先保存即可测试。"""
    name: str = ""
    api_base: str
    api_key: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 2000


@app.post("/api/llm/test")
def test_llm(req: LLMTestRequest):
    """测试 LLM 连通性，返回详细诊断信息。

    流程：
    1. 配置校验：api_base 清理反引号、检测 /v1 后缀缺失
    2. 实际调用：发送一条简短消息验证连通性

    返回：
        {
            "ok": bool,
            "provider": str,       # 识别出的 provider 名（取 host）
            "model": str,
            "api_base": str,       # 清理后的 api_base
            "response": str,       # LLM 的响应文本（成功时）
            "error": str,          # 失败时的诊断信息
            "config_hint": str,    # 配置问题提示（如缺 /v1）
        }
    """
    client = LLMClient(req.model_dump())

    # 1. 配置校验
    hint = client.validate()
    if hint:
        return {
            "ok": False,
            "provider": "",
            "model": client.model,
            "api_base": client.api_base,
            "response": "",
            "error": f"配置问题：{hint}",
            "config_hint": hint,
        }

    # 2. 实际调用测试（发一条简短消息）
    resp, err = client.chat(
        [{"role": "user", "content": "请回复 ok"}],
        temperature=0,
    )
    if resp:
        return {
            "ok": True,
            "provider": client.api_base.split("//")[-1].split("/")[0],
            "model": client.model,
            "api_base": client.api_base,
            "response": resp[:200],
            "error": "",
            "config_hint": "",
        }
    return {
        "ok": False,
        "provider": client.api_base.split("//")[-1].split("/")[0],
        "model": client.model,
        "api_base": client.api_base,
        "response": "",
        "error": err,
        "config_hint": "",
    }


# ============================================================================
# 启动
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8766)
