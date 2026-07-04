"""待办事项自动提取器。

从聊天消息（中西/西语混合）中识别待办语义，产出 Todo 候选。
策略：
1. 规则匹配（西语 + 中文 + 英文）—— 高 precision，作为默认本地兜底
2. 可选 LLM 增强 —— 用户配置 API Key 后调用，准确率更高

支持的待办语义模式：
- 时间承诺：明天/下周/周四发货，envío mañana, shipment next Monday
- 行动请求：请报价/请发样品/请确认，por favor cotiza, please send
- 会议约定：周五会议/llamada el viernes
- 数字 + 单位：30% 订金、50 unidades
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from ..storage.models import Message, Todo


# ----------------------------------------------------------------------------
# 时间触发词 → 相对偏移
# ----------------------------------------------------------------------------
def _resolve_due_phrase(text: str, now: datetime) -> Tuple[Optional[int], Optional[str]]:
    """从文本里识别截止时间短语，返回 (due_ts, time_label)。"""
    text_lower = text.lower()

    # 明天 / mañana / tomorrow
    if re.search(r"明天|mañana|tomorrow", text_lower):
        due = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        return int(due.timestamp()), "明天"

    # 后天
    if "后天" in text:
        due = (now + timedelta(days=2)).replace(hour=18, minute=0, second=0, microsecond=0)
        return int(due.timestamp()), "后天"

    # 下周 / next week / semana que viene
    if re.search(r"下周|next week|semana que viene|próxima semana", text_lower):
        due = (now + timedelta(weeks=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        return int(due.timestamp()), "下周"

    # 周X
    weekday_match = re.search(r"(周一|周二|周三|周四|周五|周六|周日|星期一|星期二|星期三|星期四|星期五|星期六|星期日|lunes|martes|miércoles|jueves|viernes|sábado|domingo)", text_lower)
    if weekday_match:
        weekday_map = {
            "周一": 0, "星期一": 0, "lunes": 0,
            "周二": 1, "星期二": 1, "martes": 1,
            "周三": 2, "星期三": 2, "miércoles": 2, "miercoles": 2,
            "周四": 3, "星期四": 3, "jueves": 3,
            "周五": 4, "星期五": 4, "viernes": 4,
            "周六": 5, "星期六": 5, "sábado": 5, "sabado": 5,
            "周日": 6, "星期日": 6, "domingo": 6,
        }
        kw = weekday_match.group(1)
        target_wd = weekday_map.get(kw)
        if target_wd is not None:
            today_wd = now.weekday()
            days_ahead = (target_wd - today_wd) % 7
            if days_ahead == 0:
                days_ahead = 7  # "周五" 在周五说，默认下周五
            due = (now + timedelta(days=days_ahead)).replace(hour=18, minute=0, second=0, microsecond=0)
            return int(due.timestamp()), kw

    # X 天后 / in X days / en X días
    m = re.search(r"(\d+)\s*(?:天之后|天后|days|días|dias)", text_lower)
    if m:
        days = int(m.group(1))
        due = (now + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)
        return int(due.timestamp()), f"{days}天后"

    return None, None


# ----------------------------------------------------------------------------
# 动作触发词
# ----------------------------------------------------------------------------
# 西/中/英三语的"待办动作"模式
# 西语动词用词干形式以覆盖各种变位（despachar→despach, confirmar→confirm, etc.）
ACTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"报价|coti[zs]|quote|quotation", re.IGNORECASE), "报价"),
    (re.compile(r"发货|enví|envi[ao]s?|ship|shipment|despach", re.IGNORECASE), "发货"),
    (re.compile(r"发样品|送样品|muestra|sample", re.IGNORECASE), "发样品"),
    (re.compile(r"确认|confirm", re.IGNORECASE), "确认"),
    (re.compile(r"付款|pago|pagar|pagamos|pay|payment|转账|transferencia", re.IGNORECASE), "付款"),
    (re.compile(r"会议|开会|llamada|reuni[óo]n|meeting|call", re.IGNORECASE), "会议"),
    (re.compile(r"下单|hacer pedido|place order|下订单", re.IGNORECASE), "下单"),
    (re.compile(r"回复|respond|reply|contest", re.IGNORECASE), "回复"),
    (re.compile(r"检查|revis|check|verificar", re.IGNORECASE), "检查"),
    (re.compile(r"准备|prepar|prepare", re.IGNORECASE), "准备"),
    (re.compile(r"提供|proporcion|provide|enviar detalle", re.IGNORECASE), "提供"),
]

# 待办强度词（提高命中可信度）
TODO_HINT_WORDS = re.compile(
    r"请|por favor|pls|please|麻烦|need to|tengo que|hay que|需要|记得|no olvidar|don't forget",
    re.IGNORECASE,
)


@dataclass
class ExtractedTodo:
    """从消息里抽出的待办候选。"""

    title: str
    detail: str
    due_ts: Optional[int]
    time_label: Optional[str]
    action_label: str
    priority: str  # low / normal / high / urgent
    raw_excerpt: str  # 触发命中的原文片段


def extract_from_message(msg: Message, now: Optional[datetime] = None) -> List[ExtractedTodo]:
    """从单条消息提取待办候选。

    一条消息可能产出多个候选（不同动作）。
    """
    if not msg.content or msg.direction == "out":
        # 仅处理对方发来的消息（我发出的通常是承诺，但暂不提取以减少噪音）
        # 注：可按需求调整为也提取"我发出的承诺"
        return []
    now = now or datetime.now()

    results: List[ExtractedTodo] = []
    content = msg.content

    # 1. 找时间
    due_ts, time_label = _resolve_due_phrase(content, now)

    # 2. 找动作
    matched_actions: List[str] = []
    for pat, label in ACTION_PATTERNS:
        if pat.search(content):
            if label not in matched_actions:
                matched_actions.append(label)

    if not matched_actions:
        return []

    # 3. 是否带"请"等强度词 → 升级优先级
    has_hint = bool(TODO_HINT_WORDS.search(content))

    # 4. 截取原文片段（动作关键词前后 30 字符）
    for action in matched_actions:
        pat = next(p for p, lbl in ACTION_PATTERNS if lbl == action)
        m = pat.search(content)
        if not m:
            continue
        start = max(0, m.start() - 30)
        end = min(len(content), m.end() + 30)
        excerpt = content[start:end].strip()

        title = f"{action}：{msg.sender or '客户'}" if msg.sender else action
        if time_label:
            title = f"{time_label}{action}"

        # 优先级判定
        if has_hint and due_ts is not None:
            priority = "high"
        elif has_hint or due_ts is not None:
            priority = "normal"
        else:
            priority = "low"

        results.append(
            ExtractedTodo(
                title=title,
                detail=excerpt,
                due_ts=due_ts,
                time_label=time_label,
                action_label=action,
                priority=priority,
                raw_excerpt=excerpt,
            )
        )

    return results


def extract_from_messages(
    messages: List[Message], now: Optional[datetime] = None
) -> List[Tuple[Message, ExtractedTodo]]:
    """批量提取，返回 (message, ExtractedTodo) 对。"""
    out: List[Tuple[Message, ExtractedTodo]] = []
    for m in messages:
        for t in extract_from_message(m, now=now):
            out.append((m, t))
    return out


def to_todo(message: Message, extracted: ExtractedTodo) -> Todo:
    """把 ExtractedTodo 转成待写入数据库的 Todo 模型。"""
    return Todo(
        contact_id=message.contact_id,
        message_id=message.id,
        title=extracted.title,
        detail=extracted.detail,
        due_ts=extracted.due_ts,
        status="pending",
        source="auto_extract",
        priority=extracted.priority,
    )
