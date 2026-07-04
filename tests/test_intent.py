"""测试意图识别（规则兜底）。"""

from __future__ import annotations

from backend.intent import classify, classify_batch
from backend.intent.rule_fallback import classify as rule_classify


class TestRuleFallback:
    def test_quotation_spanish(self):
        intent, conf = rule_classify("¿Me puedes cotizar 500 unidades?")
        assert intent == "quotation"
        assert conf > 0.5

    def test_quotation_chinese(self):
        intent, _ = rule_classify("请给我报个价")
        assert intent == "quotation"

    def test_order_intent(self):
        intent, _ = rule_classify("Quiero hacer el pedido formal")
        assert intent == "order_intent"

    def test_payment(self):
        intent, _ = rule_classify("El pago lo hago el jueves por transferencia")
        assert intent == "payment"

    def test_logistics(self):
        intent, _ = rule_classify("¿Pueden enviar mañana por DHL?")
        assert intent == "logistics"

    def test_complaint(self):
        intent, _ = rule_classify("50 unidades llegaron defectuosas, quiero reclamo")
        assert intent == "complaint"

    def test_meeting(self):
        intent, _ = rule_classify("agendar una reunión el viernes")
        assert intent == "meeting"

    def test_greeting(self):
        # 纯问候语应被识别为 greeting
        intent, _ = rule_classify("Hola!")
        assert intent == "greeting"

    def test_greeting_buenos_dias(self):
        # "buenos días" 多词问候也应识别
        intent, _ = rule_classify("buenos días")
        assert intent == "greeting"

    def test_thanks(self):
        intent, _ = rule_classify("Muchas gracias por la confirmación")
        assert intent == "thanks"

    def test_farewell(self):
        intent, _ = rule_classify("Chao!")
        assert intent == "farewell"

    def test_farewell_hasta_luego(self):
        intent, _ = rule_classify("hasta luego")
        assert intent == "farewell"

    def test_other_when_no_match(self):
        intent, conf = rule_classify("El clima está agradable hoy")
        assert intent == "other"
        assert conf < 0.5


class TestClassifyFacade:
    """classify 便捷函数（默认 engine 在沙箱中无模型，应回退到规则）。"""

    def test_classify_single(self):
        intent, _ = classify("cotización please")
        assert intent == "quotation"

    def test_classify_batch(self):
        texts = [
            "cotizar 500 unidades",
            "hacer el pedido",
            "transferencia bancaria",
        ]
        results = classify_batch(texts)
        assert len(results) == 3
        assert results[0][0] == "quotation"
        assert results[1][0] == "order_intent"
        assert results[2][0] == "payment"
