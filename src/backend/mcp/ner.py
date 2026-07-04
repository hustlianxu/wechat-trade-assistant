"""规则式 NER（命名实体识别）—— MCP 自然语言解析的本地兜底方案。

不依赖任何外部模型，纯正则 + 关键词词典，可识别：
- 时间短语（"昨天"、"上周"、"最近一个月"、"近 7 天"、"2024-03"…）
- 联系人名（西班牙语常见名 + 用户备注名 + "和 XXX 的聊天" 句式）
- 关键词（"价格"、"报价"、"订单"、"发货" 等外贸领域词典）
- 意图类别（订单/询价/投诉/物流/付款 等）
- 动作（"对比"、"总结"、"列出"、"查询"）

设计原则：
1. 高 precision > 高 recall，宁可漏识别让用户再补一句，也不能乱匹配
2. 每个识别器独立，便于单测
3. 输出统一为 list[str]，避免互相污染
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

# 常见西班牙语姓名（外贸客户高频），后续可由 contacts 表动态扩展
SPANISH_NAMES = {
    "juan", "maria", "carlos", "pedro", "luis", "jorge", "ana", "sofia",
    "diego", "fernando", "ricardo", "miguel", "pablo", "elena", "carmen",
    "javier", "raul", "sergio", "andres", "lucia", "patricia", "daniel",
    "alejandro", "roberto", "marta", "cristina", "oscar", "adriana",
    # 葡语/南美混合常见
    "bruno", "gabriel", "rafael", "felipe", "vinicius", "camila",
}

# 外贸领域关键词词典（中西双语），用于在没有显式引号时辅助提取关键词
DOMAIN_KEYWORDS = {
    "价格": ["precio", "price", "precios"],
    "报价": ["cotización", "cotizacion", "quote", "quotation"],
    "订单": ["pedido", "orden", "order"],
    "发货": ["envío", "envio", "shipment", "ship"],
    "物流": ["logística", "logistica", "logistics", "aduana", "海关"],
    "付款": ["pago", "payment", "transferencia", "转账"],
    "样品": ["muestra", "sample"],
    "质量": ["calidad", "quality"],
    "交期": ["entrega", "delivery"],
    "合同": ["contrato", "contract"],
    "发票": ["factura", "invoice"],
    "运费": ["flete", "freight"],
    "库存": ["stock", "inventario"],
    "包装": ["embalaje", "packing"],
}

# 意图标签（与 intent/ 模块对齐）
INTENT_KEYWORDS = {
    "order_intent": ["订单", "下单", "pedido", "orden", "order"],
    "inquiry": ["询价", "咨询", "问一下", "consulta", "pregunta"],
    "quotation": ["报价", "cotización", "quote"],
    "complaint": ["投诉", "抱怨", "问题", "queja", "problema"],
    "logistics": ["物流", "发货", "运输", "envío", "aduana"],
    "payment": ["付款", "汇款", "pago", "transferencia"],
    "meeting": ["会议", "见面", "reunión", "llamada"],
}

# 动作关键词 → QueryFilter.intent_action
ACTION_PATTERNS = [
    ("compare", re.compile(r"对比|比较|versus|vs\b|相比", re.IGNORECASE)),
    ("summarize", re.compile(r"总结|摘要|概览|概括|summar", re.IGNORECASE)),
    ("list", re.compile(r"列出|列表|展示|显示|罗列|list\b|show", re.IGNORECASE)),
]


@dataclass
class ParsedEntities:
    """NER 抽取结果。"""

    contact_keywords: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    relative_time: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    include_todos: bool = False
    todo_status: Optional[str] = None
    intent_action: Optional[str] = None
    matched_phrases: List[str] = field(default_factory=list)  # 调试用：记录各匹配片段


# ----------------------------------------------------------------------------
# 时间解析
# ----------------------------------------------------------------------------
# 中文相对时间 → {start_offset_days, end_offset_days} 相对"今天 00:00"
# offset 为相对"今天结束"的负偏移天数。0 表示今天，-1 表示昨天，等
RELATIVE_TIME_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"今天|today"), "今天"),
    (re.compile(r"昨天|ayer|yesterday"), "昨天"),
    (re.compile(r"前天"), "前天"),
    (re.compile(r"本周|这周|this week"), "本周"),
    (re.compile(r"上周|last week|semana pasada"), "上周"),
    (re.compile(r"本周至今|这周到今天"), "本周至今"),
    (re.compile(r"近\s?7\s?天|最近7天|过去7天|últimos 7 días"), "近7天"),
    (re.compile(r"近\s?30\s?天|最近30天|过去30天|最近一个月|近一个月|último mes|últimos 30 días"), "近30天"),
    (re.compile(r"近\s?3\s?天|最近3天|过去3天"), "近3天"),
    (re.compile(r"本月|这个月|this month|este mes"), "本月"),
    (re.compile(r"上月|上个月|last month|mes pasado"), "上月"),
    (re.compile(r"最近|recently|últimamente"), "最近"),
]


def resolve_relative_time(phrase: str, now: Optional[datetime] = None) -> Tuple[Optional[int], Optional[int]]:
    """把相对时间短语解析为 (start_ts, end_ts) Unix 秒。

    返回 (None, None) 表示未识别。
    """
    if now is None:
        now = datetime.now()

    # 今天 00:00 与 23:59:59
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1) - timedelta(seconds=1)

    p = phrase
    if p == "今天":
        return int(today_start.timestamp()), int(today_end.timestamp())
    if p == "昨天":
        s = today_start - timedelta(days=1)
        e = s + timedelta(days=1) - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if p == "前天":
        s = today_start - timedelta(days=2)
        e = s + timedelta(days=1) - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if p == "近3天":
        s = today_start - timedelta(days=2)
        return int(s.timestamp()), int(today_end.timestamp())
    if p == "近7天":
        s = today_start - timedelta(days=6)
        return int(s.timestamp()), int(today_end.timestamp())
    if p == "近30天" or p == "最近一个月" or p == "近一个月":
        s = today_start - timedelta(days=29)
        return int(s.timestamp()), int(today_end.timestamp())
    if p == "最近":
        s = today_start - timedelta(days=7)
        return int(s.timestamp()), int(today_end.timestamp())
    if p == "本周":
        # 周一为一周开始
        weekday = today_start.weekday()  # 0=Mon
        s = today_start - timedelta(days=weekday)
        e = s + timedelta(days=7) - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if p == "上周":
        weekday = today_start.weekday()
        this_mon = today_start - timedelta(days=weekday)
        s = this_mon - timedelta(days=7)
        e = this_mon - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if p == "本周至今":
        weekday = today_start.weekday()
        s = today_start - timedelta(days=weekday)
        return int(s.timestamp()), int(now.timestamp())
    if p == "本月":
        s = today_start.replace(day=1)
        # 月末
        if now.month == 12:
            e = s.replace(year=now.year + 1, month=1) - timedelta(seconds=1)
        else:
            e = s.replace(month=now.month + 1) - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    if p == "上月":
        if now.month == 1:
            s = today_start.replace(year=now.year - 1, month=12, day=1)
        else:
            s = today_start.replace(month=now.month - 1, day=1)
        e = today_start.replace(day=1) - timedelta(seconds=1)
        return int(s.timestamp()), int(e.timestamp())
    return None, None


# ----------------------------------------------------------------------------
# 联系人识别
# ----------------------------------------------------------------------------
# 句式 1：和 XXX 的聊天 / 跟 XXX / 与 XXX
CONTACT_WITH_PATTERN = re.compile(
    r"(?:和|跟|与|with)\s*([A-Za-zÀ-ÿ]{2,20})\s*(?:的|聊|讨论|沟通|对话|mention|talk)",
    re.IGNORECASE,
)
# 句式 2：XXX 的聊天 / XXX 聊天 / XXX 关于
CONTACT_OWNER_PATTERN = re.compile(
    r"([A-Za-zÀ-ÿ]{2,20})\s*(?:的聊天|聊天|关于|聊到)",
    re.IGNORECASE,
)
# 句式 3：显式引号 "Juan" 或 'Juan'
CONTACT_QUOTED_PATTERN = re.compile(r"[\"'“”‘’]([A-Za-zÀ-ÿ\s]{2,30})[\"'“”‘’]")


def extract_contacts(text: str, known_contacts: Optional[List[str]] = None) -> List[str]:
    """从自然语言中提取联系人名。

    策略（按优先级）：
    1. 引号包裹的字符串
    2. "和/跟/与 X 的聊天" 句式
    3. "X 的聊天" 句式
    4. 已知客户名（备注/昵称）直接命中
    5. 西班牙语常见名兜底
    """
    found: List[str] = []
    seen = set()

    def add(name: str) -> None:
        name = name.strip().strip(",.，。")
        if not name:
            return
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(name)

    # 1) 引号
    for m in CONTACT_QUOTED_PATTERN.finditer(text):
        add(m.group(1))

    # 2) "和/跟/与 X 的聊天"
    for m in CONTACT_WITH_PATTERN.finditer(text):
        add(m.group(1))

    # 3) "X 的聊天"
    for m in CONTACT_OWNER_PATTERN.finditer(text):
        add(m.group(1))

    # 4) 已知客户名直接命中（用户备注/昵称）
    if known_contacts:
        text_lower = text.lower()
        for name in known_contacts:
            if not name:
                continue
            if name.lower() in text_lower:
                add(name)

    # 5) 西班牙语常见名兜底
    text_lower = text.lower()
    # 词边界匹配（避免 "and" 之类误命中）
    for name in SPANISH_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", text_lower):
            add(name.capitalize())

    return found


# ----------------------------------------------------------------------------
# 关键词识别
# ----------------------------------------------------------------------------
# 显式引号也是关键词来源
KEYWORD_QUOTED = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{1,40})[\"'“”‘’]")


def expand_keyword_aliases(keywords: List[str]) -> List[str]:
    """把中文领域关键词扩展为多语言同义词列表。

    外贸场景下用户用中文提问（如"订单"），但聊天记录是西班牙语（"pedido"）。
    本函数把每个关键词映射到 DOMAIN_KEYWORDS 中的全部同义词，使 FTS5 检索
    能跨语言命中。

    示例：
        ["订单"] → ["订单", "pedido", "orden", "order"]
        ["价格", "Juan"] → ["价格", "precio", "price", "precios", "Juan"]
    """
    expanded: List[str] = []
    seen = set()
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            expanded.append(kw)
        # 若 kw 是 DOMAIN_KEYWORDS 的中文 key，加入其所有外文别名
        if kw in DOMAIN_KEYWORDS:
            for alias in DOMAIN_KEYWORDS[kw]:
                alias_lower = alias.lower()
                if alias_lower not in seen:
                    seen.add(alias_lower)
                    expanded.append(alias)
    return expanded


def extract_keywords(text: str, contacts: List[str]) -> List[str]:
    """从自然语言中提取关键词。

    来源：
    1. 引号包裹的词（剔除已被识别为联系人的）
    2. 域词典命中（价格/订单/发货…）
    3. "关于 X 的讨论" 句式
    """
    found: List[str] = []
    seen = set()
    contact_lower = {c.lower() for c in contacts}

    def add(kw: str) -> None:
        kw = kw.strip().strip(",.，。")
        if not kw or len(kw) < 1:
            return
        if kw.lower() in contact_lower:
            return  # 已被识别为联系人
        if kw.lower() in seen:
            return
        seen.add(kw.lower())
        found.append(kw)

    # 1) 引号
    for m in KEYWORD_QUOTED.finditer(text):
        add(m.group(1))

    # 2) 域词典：中文 key 本身及其外文别名任一命中即收录
    text_lower = text.lower()
    for cn, aliases in DOMAIN_KEYWORDS.items():
        # 中文 key 直接命中（如查询里的"订单"）
        if cn in text:
            add(cn)
            continue
        # 外文别名命中
        for alias in aliases:
            if alias.lower() in text_lower:
                add(cn)
                break

    # 3) "关于 X 的讨论 / 关于 X 的聊天"
    m = re.search(r"关于\s*([^，。,\s]{1,20})\s*的(?:讨论|聊天|对话|沟通)", text)
    if m:
        add(m.group(1))

    return found


# ----------------------------------------------------------------------------
# 意图识别
# ----------------------------------------------------------------------------
def extract_intents(text: str) -> List[str]:
    """从查询里识别意图过滤条件。"""
    found: List[str] = []
    text_lower = text.lower()
    for intent, kws in INTENT_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text_lower:
                if intent not in found:
                    found.append(intent)
                break
    return found


# ----------------------------------------------------------------------------
# 动作识别
# ----------------------------------------------------------------------------
def extract_action(text: str) -> Optional[str]:
    for action, pat in ACTION_PATTERNS:
        if pat.search(text):
            return action
    return None


# ----------------------------------------------------------------------------
# 待办识别
# ----------------------------------------------------------------------------
TODO_PATTERN = re.compile(r"待办|todo|任务", re.IGNORECASE)
TODO_STATUS_PATTERNS = [
    ("pending", re.compile(r"未处理|待处理|pending|por hacer|未完成")),
    ("doing", re.compile(r"进行中|处理中|in progress|en progreso")),
    ("done", re.compile(r"已完成|已处理|done|completado")),
    ("cancelled", re.compile(r"已取消|cancelled|cancelado")),
]


def extract_todo_signal(text: str) -> Tuple[bool, Optional[str]]:
    """识别是否涉及待办查询，并返回状态过滤。"""
    if not TODO_PATTERN.search(text):
        return False, None
    status: Optional[str] = None
    for s, pat in TODO_STATUS_PATTERNS:
        if pat.search(text):
            status = s
            break
    return True, status


# ----------------------------------------------------------------------------
# 时间提取（顶层入口）
# ----------------------------------------------------------------------------
def extract_time(text: str, now: Optional[datetime] = None) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """返回 (相对时间短语, start_ts, end_ts)。"""
    for pat, label in RELATIVE_TIME_PATTERNS:
        m = pat.search(text)
        if m:
            s, e = resolve_relative_time(label, now=now)
            return label, s, e
    return None, None, None


# ----------------------------------------------------------------------------
# 顶层 NER 入口
# ----------------------------------------------------------------------------
def parse(text: str, known_contacts: Optional[List[str]] = None, now: Optional[datetime] = None) -> ParsedEntities:
    """对自然语言查询做规则 NER，返回 ParsedEntities。"""
    contacts = extract_contacts(text, known_contacts=known_contacts)
    keywords = extract_keywords(text, contacts)
    intents = extract_intents(text)
    action = extract_action(text)
    rel_time, start_ts, end_ts = extract_time(text, now=now)
    include_todos, todo_status = extract_todo_signal(text)

    matched_phrases: List[str] = []
    if contacts:
        matched_phrases.append(f"contacts={contacts}")
    if keywords:
        matched_phrases.append(f"keywords={keywords}")
    if intents:
        matched_phrases.append(f"intents={intents}")
    if rel_time:
        matched_phrases.append(f"time={rel_time}")
    if action:
        matched_phrases.append(f"action={action}")
    if include_todos:
        matched_phrases.append(f"todos(status={todo_status})")

    return ParsedEntities(
        contact_keywords=contacts,
        keywords=keywords,
        intents=intents,
        relative_time=rel_time,
        start_ts=start_ts,
        end_ts=end_ts,
        include_todos=include_todos,
        todo_status=todo_status,
        intent_action=action,
        matched_phrases=matched_phrases,
    )
