"""意图识别模块。

对外暴露：
- IntentoEngine：Intento-v1-xlmr 模型封装（含本地兜底）
- classify：便捷函数，优先用模型，失败回退规则
- rule_fallback：纯规则实现
"""

from pathlib import Path
from typing import List, Optional, Tuple

from . import rule_fallback
from .intento_engine import IntentoEngine, get_default_engine


def classify(text: str, engine: Optional[IntentoEngine] = None) -> Tuple[str, float]:
    """对单条文本做意图分类。

    优先使用传入的 engine（或默认 engine）；若不可用则用规则。
    """
    if engine is None:
        engine = get_default_engine()
    return engine.classify(text)


def classify_batch(
    texts: List[str], engine: Optional[IntentoEngine] = None
) -> List[Tuple[str, float]]:
    if engine is None:
        engine = get_default_engine()
    return engine.classify_batch(texts)


__all__ = [
    "IntentoEngine",
    "get_default_engine",
    "classify",
    "classify_batch",
    "rule_fallback",
]
