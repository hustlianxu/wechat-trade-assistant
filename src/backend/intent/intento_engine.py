"""Intento-v1-xlmr 模型封装。

参考：https://huggingface.co/luigicfilho/Intento-v1-xlmr
基于 XLM-RoBERTa 微调的多语言意图分类模型，支持 101 种意图，含西班牙语。

设计：
- 模型未下载/transformers 未安装时，自动回退到 rule_fallback
- 模型路径由 settings 决定，默认 models/intent/
- 仅对中文/西语/英语文本分类，其他文本返回 "other"
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from . import rule_fallback


class IntentoEngine:
    """Intento-v1 模型封装，含本地兜底。"""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        device: str = "cpu",
        threshold: float = 0.4,
    ) -> None:
        """
        Args:
            model_path: 模型目录（含 config.json、pytorch_model.bin 等）
            device: 推理设备，桌面端默认 cpu
            threshold: 置信度阈值，低于此值回退到规则
        """
        self.model_path = Path(model_path) if model_path else None
        self.device = device
        self.threshold = threshold
        self._model = None
        self._tokenizer = None
        self._labels: List[str] = []
        self._loaded = False
        self._load_error: Optional[str] = None

    def is_available(self) -> bool:
        """模型是否可用（已下载且 transformers 已装）。"""
        if self._loaded and self._model is not None:
            return True
        if self.model_path is None or not self.model_path.exists():
            return False
        try:
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def load(self) -> bool:
        """加载模型。成功返回 True，失败返回 False 并记录错误。"""
        if self._loaded:
            return True
        if self.model_path is None or not self.model_path.exists():
            self._load_error = f"模型路径不存在：{self.model_path}"
            return False
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_path))
            self._model = AutoModelForSequenceClassification.from_pretrained(
                str(self.model_path)
            )
            self._model.to(self.device)
            self._model.eval()
            self._labels = list(self._model.config.id2label.values())
            self._loaded = True
            return True
        except Exception as e:  # noqa: BLE001
            self._load_error = f"{type(e).__name__}: {e}"
            return False

    def classify(self, text: str) -> Tuple[str, float]:
        """对单条文本分类，返回 (intent, confidence)。

        若模型不可用或置信度低于阈值，回退到 rule_fallback。
        """
        if not text or not text.strip():
            return "other", 0.2

        if not self.is_available() and not self.load():
            return rule_fallback.classify(text)

        try:
            import torch

            inputs = self._tokenizer(  # type: ignore[union-attr]
                text, return_tensors="pt", truncation=True, max_length=128
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                logits = self._model(**inputs).logits  # type: ignore[union-attr]
            probs = torch.softmax(logits, dim=-1)[0]
            idx = int(probs.argmax().item())
            confidence = float(probs[idx].item())
            label = self._labels[idx] if self._labels else "other"
            # 置信度太低 → 回退规则
            if confidence < self.threshold:
                rule_label, rule_conf = rule_fallback.classify(text)
                # 取置信度更高的那个
                if rule_conf > confidence:
                    return rule_label, rule_conf
            return label, confidence
        except Exception as e:  # noqa: BLE001
            print(f"[intent] 模型推理失败，回退规则：{type(e).__name__}: {e}")
            return rule_fallback.classify(text)

    def classify_batch(self, texts: List[str]) -> List[Tuple[str, float]]:
        """批量分类。"""
        return [self.classify(t) for t in texts]


# 模块级单例
_default_engine: Optional[IntentoEngine] = None


def get_default_engine(model_path: Optional[Path] = None) -> IntentoEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = IntentoEngine(model_path=model_path)
    return _default_engine
