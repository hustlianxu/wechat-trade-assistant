"""LLM 集成：多 LLM 配置、意图识别、待办事项提取、会话总结。

支持配置多个 LLM provider（OpenAI / DeepSeek / Claude / 本地 Ollama 等），
通过 active_llm 名称切换当前使用的 provider。
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Optional


# ============================================================================
# LLM 客户端
# ============================================================================
class LLMClient:
    """OpenAI 兼容的 LLM 客户端（支持 OpenAI / DeepSeek / Moonshot / Ollama 等）。"""

    def __init__(self, config: dict):
        self.name = config.get("name", "")
        self.api_base = config.get("api_base", "").rstrip("/")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "")
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens", 2000)

    @property
    def available(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    def chat(self, messages: list[dict], temperature: Optional[float] = None) -> Optional[str]:
        """调用 chat/completions 接口。"""
        if not self.available:
            return None

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": self.max_tokens,
        }

        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, KeyError, TimeoutError):
            return None


def get_active_llm(config: dict) -> Optional[LLMClient]:
    """从配置中获取当前激活的 LLM 客户端。"""
    active_name = config.get("active_llm", "")
    providers = config.get("llm_providers", [])
    for p in providers:
        if p.get("name") == active_name:
            return LLMClient(p)
    # 如果没有激活的，尝试第一个可用的
    for p in providers:
        client = LLMClient(p)
        if client.available:
            return client
    return None


# ============================================================================
# 意图识别
# ============================================================================
INTENT_SYSTEM_PROMPT = """你是一个外贸业务意图识别助手。分析微信聊天消息，识别客户的意图类型。

意图分类：
- greeting: 问候/打招呼
- inquiry: 询盘/产品咨询
- quote: 报价/价格相关
- order: 下单/订单相关
- payment: 付款/汇款相关
- shipping: 物流/发货相关
- complaint: 投诉/售后
- negotiation: 议价/谈判
- samples: 样品相关
- catalog: 目录/产品资料索取
- meeting: 约见面/视频会议
- other: 其他

只返回 JSON 格式：
{"intent": "意图名", "confidence": 0.0-1.0, "summary": "一句话概述客户意图"}"""


def classify_intent(messages: list[dict], llm: LLMClient) -> dict:
    """识别会话意图。

    messages: [{"sender": "对方/自己", "content": "消息内容", "time": "时间"}]
    返回：{"intent": "...", "confidence": 0.9, "summary": "..."}
    """
    # 构建对话文本
    dialogue = "\n".join(
        f"[{m.get('time', '')}] {m.get('sender', '?')}: {m.get('content', '')}"
        for m in messages[-30:]  # 最近30条
    )

    resp = llm.chat([
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"请分析以下对话的意图：\n\n{dialogue}"},
    ], temperature=0.1)

    if resp:
        try:
            # 尝试提取 JSON（可能被 ```json 包裹）
            text = resp.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return {"intent": "other", "confidence": 0.5, "summary": resp[:200]}
    return {"intent": "error", "confidence": 0, "summary": "LLM 分析失败"}


# ============================================================================
# 待办事项提取
# ============================================================================
TODO_SYSTEM_PROMPT = """你是一个外贸业务待办事项提取助手。从微信聊天中提取需要跟进的待办事项。

只提取明确的待办（需要采取行动的事项），忽略普通对话。
返回 JSON 数组格式：
[
  {
    "title": "待办标题（简短）",
    "detail": "详细描述",
    "due": "截止时间（如有，格式 YYYY-MM-DD 或 '尽快'）",
    "assignee": "负责人（对方/自己）",
    "priority": "high/medium/low"
  }
]

如果没有待办，返回空数组 []。"""


def extract_todos(messages: list[dict], llm: LLMClient) -> list[dict]:
    """从会话中提取待办事项。"""
    dialogue = "\n".join(
        f"[{m.get('time', '')}] {m.get('sender', '?')}: {m.get('content', '')}"
        for m in messages[-50:]  # 最近50条
    )

    resp = llm.chat([
        {"role": "system", "content": TODO_SYSTEM_PROMPT},
        {"role": "user", "content": f"请从以下对话中提取待办事项：\n\n{dialogue}"},
    ], temperature=0.1)

    if resp:
        try:
            text = resp.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, IndexError):
            pass
    return []


# ============================================================================
# 会话总结
# ============================================================================
SUMMARY_SYSTEM_PROMPT = """你是一个外贸业务助手。请总结以下微信对话的关键信息：

1. 对话主题（一句话）
2. 关键讨论点（要点列表）
3. 客户需求/关注点
4. 已达成的一致
5. 待解决的问题

用中文输出，简洁明了。"""


def summarize_conversation(messages: list[dict], llm: LLMClient) -> str:
    """总结会话内容。"""
    dialogue = "\n".join(
        f"[{m.get('time', '')}] {m.get('sender', '?')}: {m.get('content', '')}"
        for m in messages[-100:]  # 最近100条
    )

    resp = llm.chat([
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": f"请总结以下对话：\n\n{dialogue}"},
    ], temperature=0.3)

    return resp or "总结生成失败"


# ============================================================================
# 规则兜底：无 LLM 时的简单意图识别
# ============================================================================
INTENT_KEYWORDS = {
    "greeting": ["你好", "hola", "hello", "hi", "早上好", "下午好", "晚上好", "buenas"],
    "inquiry": ["产品", "product", "规格", "specification", "型号", "model", "什么有", "有货", "available"],
    "quote": ["价格", "price", "报价", "quote", "多少钱", "cost", "how much", "precio"],
    "order": ["下单", "order", "订购", "购买", "buy", "purchase", "订单", "cantidad"],
    "payment": ["付款", "payment", "汇款", "transfer", "pay", "pago", "transferencia"],
    "shipping": ["发货", "ship", "物流", "logistics", "运费", "freight", "envío", "envio", "aduana"],
    "complaint": ["问题", "problem", "投诉", "complain", "坏了", "损坏", "quality", "calidad"],
    "negotiation": ["便宜", "discount", "折扣", "优惠", "negotiate", "más barato", "descuento"],
    "samples": ["样品", "sample", "muestra", "样本"],
    "catalog": ["目录", "catalog", "catálogo", "产品资料", "brochure"],
    "meeting": ["见面", "meet", "视频", "video", "llamada", "reunión"],
}


def classify_intent_rules(text: str) -> tuple[str, float]:
    """基于关键词的简单意图识别（无 LLM 时兜底）。"""
    text_lower = text.lower()
    best_intent = "other"
    best_score = 0.0
    for intent, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower) / max(len(keywords), 1)
        if score > best_score:
            best_score = score
            best_intent = intent
    return best_intent, min(best_score * 2, 1.0)  # 放大分数
