"""MCP 回复生成器：本地兜底 + 云端 LLM 双通道。

策略：
1. 若用户在设置里配置了云端 API Key（DeepSeek / OpenAI 兼容），优先用 LLM 生成自然语言回复
2. 否则用本地规则摘要（summarize_messages_local / compare_contacts_local / todo listing）
3. 任何情况下，结构化数据（messages/todos/contacts）都会一并返回给前端展示

所有 LLM 调用走 httpx，超时 30s；失败时自动降级到本地。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from ..storage.models import (
    Contact,
    Message,
    MessageSearchResult,
    QueryFilter,
    Todo,
)
from ..storage.repository import Repository
from .retriever import (
    Retriever,
    compare_contacts_local,
    summarize_messages_local,
)


class CloudLLMConfig:
    """云端 LLM 配置（OpenAI 兼容协议）。"""

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_settings(cls, settings: Dict[str, str]) -> Optional["CloudLLMConfig"]:
        """从 settings 字典构造。任一关键字段缺失返回 None。"""
        api_base = settings.get("llm_api_base", "").strip()
        api_key = settings.get("llm_api_key", "").strip()
        model = settings.get("llm_model", "").strip()
        if not (api_base and api_key and model):
            return None
        try:
            timeout = float(settings.get("llm_timeout", "30"))
        except ValueError:
            timeout = 30.0
        return cls(api_base, api_key, model, timeout=timeout)


# ----------------------------------------------------------------------------
# 提示词构造
# ----------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "你是南美外贸微信助手，负责根据用户本地微信聊天记录回答问题。"
    "请基于下方提供的真实消息内容作答，不要编造。"
    "若信息不足以回答，明确告知用户。回复用中文，简洁专业。"
    "若涉及具体订单/报价/物流等数字，必须引用对应消息原文。"
)


def _build_user_prompt(
    query: QueryFilter,
    messages: List[Message],
    contacts: List[Contact],
    todos: List[Todo],
) -> str:
    """把结构化检索结果拼成 LLM 可读的 prompt。"""
    parts: List[str] = []
    parts.append(f"用户提问：{query.raw_query}\n")

    # 客户信息
    if contacts:
        c_lines = []
        for c in contacts[:10]:
            name = c.remark or c.nickname or c.wxid
            c_lines.append(f"  - {name}（{c.region or '未知地区'}，最近意图：{c.last_intent or '无'}）")
        parts.append("相关客户：\n" + "\n".join(c_lines) + "\n")
    else:
        parts.append("相关客户：无\n")

    # 消息内容
    if messages:
        m_lines = []
        for m in messages[:40]:
            dt = datetime.fromtimestamp(m.created_ts).strftime("%Y-%m-%d %H:%M")
            sender = "我" if m.direction == "out" else "对方"
            intent_tag = f"[{m.intent}]" if m.intent else ""
            content = (m.content or "").strip().replace("\n", " ")[:200]
            m_lines.append(f"  {dt} {sender}{intent_tag}: {content}")
        parts.append("相关聊天记录（最多 40 条）：\n" + "\n".join(m_lines) + "\n")
    else:
        parts.append("相关聊天记录：无\n")

    # 待办
    if todos:
        t_lines = []
        for t in todos[:20]:
            dt = datetime.fromtimestamp(t.due_ts).strftime("%Y-%m-%d %H:%M") if t.due_ts else "无截止"
            t_lines.append(f"  - [{t.status}] {t.title}（截止：{dt}，来源：{t.source}）")
        parts.append("相关待办：\n" + "\n".join(t_lines) + "\n")

    parts.append("请基于以上信息回答用户提问。")
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# Responder
# ----------------------------------------------------------------------------
class Responder:
    """根据 QueryFilter 检索数据并生成回复（本地或云端）。"""

    def __init__(self, repo: Repository, llm_config: Optional[CloudLLMConfig] = None) -> None:
        self.repo = repo
        self.retriever = Retriever(repo)
        self.llm_config = llm_config

    def set_llm_config(self, config: Optional[CloudLLMConfig]) -> None:
        self.llm_config = config

    def answer(self, query: QueryFilter) -> MessageSearchResult:
        """主入口：解析→检索→生成回复。"""
        t0 = time.time()

        # 1. 检索
        result = self.retriever.retrieve(query)

        # 2. 生成摘要/回复
        summary, engine = self._generate_summary(query, result)

        result.summary = summary
        result.engine = engine
        result.latency_ms = int((time.time() - t0) * 1000)
        return result

    def _generate_summary(
        self, query: QueryFilter, result: MessageSearchResult
    ) -> tuple[str, str]:
        """返回 (summary, engine)。engine ∈ {'local', 'cloud'}。"""

        # 待办查询：直接列出，无需 LLM
        if query.include_todos:
            return self._format_todos(query, result.todos), "local"

        # 对比动作
        if query.intent_action == "compare" and len(result.contacts) >= 2:
            by_contact: Dict[int, List[Message]] = {}
            for m in result.messages:
                by_contact.setdefault(m.contact_id, []).append(m)
            local_summary = compare_contacts_local(by_contact, result.contacts, query)
            # 云端增强
            if self.llm_config:
                cloud = self._call_cloud(query, result, compare_mode=True)
                if cloud:
                    return cloud, "cloud"
            return local_summary, "local"

        # 摘要/列出/回答
        local_summary = summarize_messages_local(
            result.messages, result.contacts, query
        )

        if self.llm_config:
            cloud = self._call_cloud(query, result, compare_mode=False)
            if cloud:
                return cloud, "cloud"

        return local_summary, "local"

    def _format_todos(self, query: QueryFilter, todos: List[Todo]) -> str:
        if not todos:
            status_desc = f"状态={query.todo_status}" if query.todo_status else "全部状态"
            time_desc = query.relative_time or "全部时间"
            return f"未检索到符合条件的待办（{time_desc}，{status_desc}）。"
        parts = [f"共检索到 {len(todos)} 条待办："]
        for t in todos:
            dt = datetime.fromtimestamp(t.due_ts).strftime("%Y-%m-%d %H:%M") if t.due_ts else "无截止"
            parts.append(f"  - [{t.status}] {t.title}（截止：{dt}，优先级：{t.priority}）")
        return "\n".join(parts)

    def _call_cloud(
        self,
        query: QueryFilter,
        result: MessageSearchResult,
        compare_mode: bool = False,
    ) -> Optional[str]:
        """调用云端 LLM。失败时返回 None，由调用方降级。"""
        if not self.llm_config:
            return None
        try:
            user_prompt = _build_user_prompt(
                query, result.messages, result.contacts, result.todos
            )
            if compare_mode:
                user_prompt = (
                    "请对比以下不同客户的聊天记录，从意图分布、关注点、"
                    "采购紧迫度等维度做差异分析，并给出建议。\n\n" + user_prompt
                )
            url = f"{self.llm_config.api_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.llm_config.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.llm_config.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 800,
            }
            with httpx.Client(timeout=self.llm_config.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001
            # 任何异常都降级到本地，不影响可用性
            print(f"[mcp] 云端 LLM 调用失败，降级本地：{type(e).__name__}: {e}")
            return None
