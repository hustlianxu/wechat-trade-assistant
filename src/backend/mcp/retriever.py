"""MCP 检索器：把 QueryFilter 落实到本地数据库查询。

只读、纯本地，绝不联网。返回结构化的 MessageSearchResult。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from ..storage.models import (
    Contact,
    Message,
    MessageSearchResult,
    QueryFilter,
    Todo,
)
from ..storage.repository import Repository
from .ner import expand_keyword_aliases


class Retriever:
    """根据 QueryFilter 从本地库检索消息/待办/客户。"""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def retrieve(
        self,
        query: QueryFilter,
        message_limit: int = 200,
        todo_limit: int = 100,
    ) -> MessageSearchResult:
        """执行检索。

        返回的 MessageSearchResult.messages 已按时间升序排列。
        若 query.include_todos=True，则同时填 todos 字段。
        若 query.contact_keywords 命中客户，则 contacts 字段会包含这些客户。
        """
        # 1. 解析联系人 → contact_ids
        contact_ids: List[int] = list(query.contact_ids)
        matched_contacts: List[Contact] = []
        for kw in query.contact_keywords:
            contacts = self.repo.find_contacts_by_keyword(kw)
            for c in contacts:
                if c.id is not None and c.id not in contact_ids:
                    contact_ids.append(c.id)
                if c not in matched_contacts:
                    matched_contacts.append(c)

        # 构造带 contact_ids 的 QueryFilter 副本
        # 同时把中文关键词扩展为多语言同义词（用户中文提问、消息西语时跨语言命中）
        expanded_keywords = expand_keyword_aliases(query.keywords) if query.keywords else []
        effective_query = query.model_copy(
            update={"contact_ids": contact_ids, "keywords": expanded_keywords}
        )

        # 2. 检索消息
        messages = self.repo.search_messages(effective_query, limit=message_limit)

        # 3. 检索待办（如果用户问到）
        todos: List[Todo] = []
        if query.include_todos:
            todos = self.repo.list_todos(
                status=query.todo_status,
                contact_id=contact_ids[0] if len(contact_ids) == 1 else None,
                start_ts=query.start_ts,
                end_ts=query.end_ts,
            )[:todo_limit]

        # 4. 若未指定客户但消息有来源客户，也补全 contacts 字段
        if not matched_contacts:
            seen_ids = set()
            for m in messages:
                if m.contact_id in seen_ids:
                    continue
                seen_ids.add(m.contact_id)
                c = self.repo.get_contact(m.contact_id)
                if c is not None:
                    matched_contacts.append(c)

        return MessageSearchResult(
            messages=messages,
            contacts=matched_contacts,
            todos=todos,
            engine="local",
        )


# ----------------------------------------------------------------------------
# 本地摘要生成器：responder 调用，未配置 LLM 时使用
# ----------------------------------------------------------------------------
def summarize_messages_local(
    messages: List[Message],
    contacts: List[Contact],
    query: QueryFilter,
    now: Optional[datetime] = None,
) -> str:
    """生成结构化的纯文本摘要，无需 LLM。

    输出格式示例：
      已检索到 12 条与 Juan 的相关消息（上周）。
      涉及意图：order_intent(5), quotation(3), logistics(2)
      关键消息节选：
        - 2024-06-10 09:23 [Juan] Buenas, necesito cotización...
        - ...
    """
    if not messages and not contacts:
        return "未在本地库中检索到符合条件的聊天记录。可以尝试换个时间范围或客户名再问一次。"

    now = now or datetime.now()
    parts: List[str] = []

    # 头部
    contact_names = ", ".join(c.remark or c.nickname for c in contacts) or "全部客户"
    time_desc = query.relative_time or "全部时间"
    parts.append(f"已检索到 {len(messages)} 条与 {contact_names} 的相关消息（{time_desc}）。")

    # 意图统计
    intent_counts: dict[str, int] = {}
    for m in messages:
        if m.intent:
            intent_counts[m.intent] = intent_counts.get(m.intent, 0) + 1
    if intent_counts:
        sorted_intents = sorted(intent_counts.items(), key=lambda x: -x[1])
        intent_str = ", ".join(f"{k}({v})" for k, v in sorted_intents)
        parts.append(f"涉及意图：{intent_str}")

    # 关键消息节选（最多 5 条）
    if messages:
        parts.append("关键消息节选：")
        # 优先展示带意图的、对方发的、含关键词的
        scored = []
        for m in messages:
            score = 0
            if m.direction == "in":
                score += 1
            if m.intent:
                score += 2
            if any(kw.lower() in (m.content or "").lower() for kw in query.keywords):
                score += 3
            scored.append((score, m))
        scored.sort(key=lambda x: -x[0])
        for _, m in scored[:5]:
            dt = datetime.fromtimestamp(m.created_ts).strftime("%Y-%m-%d %H:%M")
            content_preview = (m.content or "").strip().replace("\n", " ")[:80]
            intent_tag = f"[{m.intent}]" if m.intent else ""
            parts.append(f"  - {dt} {intent_tag} {content_preview}")

    return "\n".join(parts)


def compare_contacts_local(
    messages_by_contact: dict[int, List[Message]],
    contacts: List[Contact],
    query: QueryFilter,
) -> str:
    """生成多客户对比摘要（本地兜底版）。"""
    if not messages_by_contact:
        return "未检索到可对比的聊天记录。"

    parts: List[str] = []
    parts.append(f"对比 {len(messages_by_contact)} 位客户的聊天记录：\n")

    contact_map = {c.id: c for c in contacts}
    for cid, msgs in messages_by_contact.items():
        c = contact_map.get(cid)
        name = (c.remark or c.nickname if c else None) or f"客户#{cid}"
        intent_counts: dict[str, int] = {}
        for m in msgs:
            if m.intent:
                intent_counts[m.intent] = intent_counts.get(m.intent, 0) + 1
        intent_str = ", ".join(f"{k}({v})" for k, v in sorted(intent_counts.items(), key=lambda x: -x[1])) or "无明确意图"
        parts.append(f"【{name}】共 {len(msgs)} 条；意图分布：{intent_str}")
        # 取一条最新消息
        if msgs:
            latest = max(msgs, key=lambda x: x.created_ts)
            dt = datetime.fromtimestamp(latest.created_ts).strftime("%Y-%m-%d %H:%M")
            preview = (latest.content or "").strip().replace("\n", " ")[:60]
            parts.append(f"  最新：{dt} {preview}")
        parts.append("")

    return "\n".join(parts).strip()
