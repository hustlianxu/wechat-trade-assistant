"""规则兜底意图分类器。

在没有 Intento-v1 模型可用时使用，提供基础的西/中/英三语意图识别。
覆盖意图类别与 Intento 主模型对齐：
  order_intent / inquiry / quotation / complaint / logistics / payment /
  meeting / greeting / thanks / farewell / other
"""

from __future__ import annotations

import re
from typing import Tuple

# 意图关键词表（按优先级排序，先匹配的胜出）
INTENT_RULES = [
    ("quotation", re.compile(
        r"coti[zs]ar|cotización|cotizacion|报[个下点]?价|估价|quote|quotation|precios?\s+de",
        re.IGNORECASE,
    )),
    ("order_intent", re.compile(
        r"pedido|orden de compra|订单|下单|hacer orden|place order|comprar",
        re.IGNORECASE,
    )),
    ("payment", re.compile(
        r"pago|transferencia|付款|汇款|转账|pay|payment|depósito|deposito",
        re.IGNORECASE,
    )),
    ("logistics", re.compile(
        r"envío|envio|enviar|envian|envían|despacho|despachar|aduana|entrega|entregar|发货|物流|运输|海关|ship|shipment|delivery|flete",
        re.IGNORECASE,
    )),
    ("complaint", re.compile(
        r"problema|queja|reclam|投诉|抱怨|质量差|质量问题|defectuos|dañad|damaged|broken|fall[ao]s?",
        re.IGNORECASE,
    )),
    ("meeting", re.compile(
        r"reunión|reunion|llamada|会议|见面|通话|meeting|call|videoconferencia",
        re.IGNORECASE,
    )),
    ("inquiry", re.compile(
        r"consulta|pregunta|询价|咨询|问一下|quiero saber|me gustaría saber|información|informacion|quote info",
        re.IGNORECASE,
    )),
    ("greeting", re.compile(
        r"^(hola|buenos\s+d[íi]as|buenas\s+(tardes|noches)|hi|hello|hey|你好|您好|早上好|下午好)[\s!¡!.。，,]*$",
        re.IGNORECASE,
    )),
    ("thanks", re.compile(
        r"gracias|thank|thanks|谢谢|多谢",
        re.IGNORECASE,
    )),
    ("farewell", re.compile(
        r"^(adiós|adios|chao|hasta luego|nos vemos|bye|goodbye|再见|拜拜)[\s!¡!.。]*$",
        re.IGNORECASE,
    )),
]

# 默认置信度：规则命中给 0.7，未命中给 0.3
RULE_HIT_CONFIDENCE = 0.7
RULE_MISS_CONFIDENCE = 0.3


def classify(text: str) -> Tuple[str, float]:
    """对单条文本做意图分类，返回 (intent, confidence)。"""
    if not text or not text.strip():
        return "other", 0.2

    for intent, pat in INTENT_RULES:
        if pat.search(text):
            return intent, RULE_HIT_CONFIDENCE

    return "other", RULE_MISS_CONFIDENCE
