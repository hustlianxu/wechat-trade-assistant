"""西班牙语外贸场景的 mock 聊天数据。

模拟 3 个南美客户（Juan / Maria / Carlos）与外贸从业者的对话，
涵盖订单、报价、物流、付款、投诉、问候等典型意图，以及若干待办触发句。

时间锚点：所有 mock 时间戳以"测试运行当下"为基准做相对偏移，
这样无论何时跑测试，"昨天/上周/最近一个月"等相对时间短语都能命中正确数据。
"""

from __future__ import annotations

from datetime import datetime

# 锚定时间：测试运行当下。NER/E2E 测试通过 now=ANCHOR_DATETIME 与之对齐。
ANCHOR_DATETIME = datetime.now()
ANCHOR_TS = int(ANCHOR_DATETIME.timestamp())

# 各时间偏移（相对 ANCHOR_TS 的秒数）
SECONDS_PER_DAY = 86400
T_MINUS = {
    "today": 0,
    "yesterday": -SECONDS_PER_DAY,
    "2days_ago": -2 * SECONDS_PER_DAY,
    "3days_ago": -3 * SECONDS_PER_DAY,
    "5days_ago": -5 * SECONDS_PER_DAY,
    "7days_ago": -7 * SECONDS_PER_DAY,
    "10days_ago": -10 * SECONDS_PER_DAY,
    "15days_ago": -15 * SECONDS_PER_DAY,
}


# ----------------------------------------------------------------------------
# 客户
# ----------------------------------------------------------------------------
MOCK_CONTACTS = [
    {
        "wxid": "juan_perez_88",
        "nickname": "Juan Pérez",
        "remark": "Juan - Chile",
        "alias": "juan_chile",
        "region": "Chile",
        "note": "智利圣地亚哥，主营建材",
    },
    {
        "wxid": "maria_gomez_22",
        "nickname": "María Gómez",
        "remark": "Maria - Colombia",
        "alias": "maria_co",
        "region": "Colombia",
        "note": "波哥大，跨境电商",
    },
    {
        "wxid": "carlos_lopez_55",
        "nickname": "Carlos López",
        "remark": "Carlos - Argentina",
        "alias": "carlos_ar",
        "region": "Argentina",
        "note": "布宜诺斯艾利斯，批发商",
    },
]


# ----------------------------------------------------------------------------
# 消息
# 每条：(wxid, msg_id, msg_type, direction, sender, content, ts_offset_key)
# direction: in=对方发来, out=我方发出
# ----------------------------------------------------------------------------
MOCK_MESSAGES = [
    # === Juan：报价 + 下单 + 物流 ===
    ("juan_perez_88", "m_j_001", "text", "in", "Juan Pérez",
     "Hola, ¿me puedes cotizar 500 unidades del modelo A-100? Necesito saber el precio con envío a Santiago.",
     "7days_ago"),
    ("juan_perez_88", "m_j_002", "text", "out", "我",
     "Hola Juan, claro. La cotización para 500 unidades de A-100 es USD 3.50 por unidad, flete aparte.",
     "7days_ago"),
    ("juan_perez_88", "m_j_003", "text", "in", "Juan Pérez",
     "Perfecto, acepto la cotización. Quiero hacer el pedido formal. ¿Pueden enviar mañana?",
     "5days_ago"),
    ("juan_perez_88", "m_j_004", "text", "out", "我",
     "Confirmado. Mañana despachamos por DHL, número de tracking te lo paso el viernes.",
     "5days_ago"),
    ("juan_perez_88", "m_j_005", "text", "in", "Juan Pérez",
     "Gracias. El pago por transferencia lo hago el jueves. ¿Me confirmas la factura proforma?",
     "3days_ago"),
    ("juan_perez_88", "m_j_006", "text", "out", "我",
     "Sí, te envío la factura proforma hoy mismo. El jueves confirmamos el pago.",
     "3days_ago"),
    ("juan_perez_88", "m_j_007", "voice", "in", "Juan Pérez",
     "Hola, ya hice la transferencia. Por favor confirmen receipt y envíen el pedido hoy.",
     "yesterday"),
    ("juan_perez_88", "m_j_008", "text", "out", "我",
     "Recibido, confirmamos pago. Despachamos hoy mismo. Gracias por tu pedido.",
     "yesterday"),

    # === Maria：询价 + 投诉质量 + 重新发货 ===
    ("maria_gomez_22", "m_m_001", "text", "in", "María Gómez",
     "Buenos días, quiero información sobre el modelo B-200. ¿Tienen stock?",
     "10days_ago"),
    ("maria_gomez_22", "m_m_002", "text", "out", "我",
     "Buenos días María. Sí, tenemos 1000 unidades en stock. Precio USD 5.20.",
     "10days_ago"),
    ("maria_gomez_22", "m_m_003", "text", "in", "María Gómez",
     "Recibí el pedido pero hay un problema: 50 unidades llegaron defectuosas. Quiero reclamo.",
     "5days_ago"),
    ("maria_gomez_22", "m_m_004", "text", "out", "我",
     "Mis disculpas María. Vamos a reenviar 50 unidades el próximo lunes sin costo.",
     "5days_ago"),
    ("maria_gomez_22", "m_m_005", "text", "in", "María Gómez",
     "Gracias por la respuesta. ¿Pueden darme un descuento del 10% en el próximo pedido?",
     "3days_ago"),

    # === Carlos：会议 + 合同 + 付款 ===
    ("carlos_lopez_55", "m_c_001", "text", "in", "Carlos López",
     "Hola, me gustaría agendar una reunión el viernes para discutir el contrato de distribución.",
     "yesterday"),
    ("carlos_lopez_55", "m_c_002", "text", "out", "我",
     "Hola Carlos, perfecto. El viernes a las 15:00 Buenos Aires te parece bien? Vía Zoom.",
     "yesterday"),
    ("carlos_lopez_55", "m_c_003", "text", "in", "Carlos López",
     "Confirmado, viernes 15:00 Zoom. Por favor envíen el borrador del contrato antes.",
     "yesterday"),
    ("carlos_lopez_55", "m_c_004", "text", "out", "我",
     "Acordado. Te envío el borrador del contrato hoy y el jueves confirmamos detalles de pago.",
     "yesterday"),
    ("carlos_lopez_55", "m_c_005", "text", "in", "Carlos López",
     "Excelente. Sobre el pago, ¿aceitan transferencia bancaria? Pregunto por las comisiones.",
     "today"),
]


def build_messages_for_insert():
    """构造可直接插入 Repository 的 Message 对象列表（不含 contact_id）。

    Returns:
        list of (wxid, Message) —— 调用方需先 upsert 联系人拿 contact_id。
    """
    from backend.storage.models import Message

    out = []
    for wxid, msg_id, msg_type, direction, sender, content, ts_key in MOCK_MESSAGES:
        ts = ANCHOR_TS + T_MINUS[ts_key]
        m = Message(
            contact_id=0,  # 占位，由调用方填
            msg_id=msg_id,
            msg_type=msg_type,
            direction=direction,
            sender=sender,
            content=content,
            created_ts=ts,
            transcribed=(msg_type == "voice"),  # mock 假定语音已转录
        )
        out.append((wxid, m))
    return out


def all_contact_names() -> list[str]:
    """返回所有 mock 客户的备注名（用于 NER 已知客户词典）。"""
    return [c["remark"] for c in MOCK_CONTACTS] + [c["nickname"] for c in MOCK_CONTACTS]
