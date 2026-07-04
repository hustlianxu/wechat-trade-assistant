"""MCP 自然语言交互模块。

对外暴露：
- QueryParser：自然语言 → QueryFilter
- Retriever：QueryFilter → 本地数据库检索
- Responder：检索 + 回复生成（本地兜底 + 云端 LLM 双通道）
- CloudLLMConfig：云端 LLM 配置

典型用法：
    from backend.mcp import QueryParser, Responder, CloudLLMConfig
    parser = QueryParser(known_contact_names=["Juan", "Maria"])
    query = parser.parse("上周和 Juan 聊了什么")
    responder = Responder(repo, llm_config=CloudLLMConfig.from_settings(settings))
    result = responder.answer(query)
    print(result.summary)
"""

from .parser import QueryParser, get_default_parser
from .responder import CloudLLMConfig, Responder
from .retriever import (
    Retriever,
    compare_contacts_local,
    summarize_messages_local,
)
from . import ner

__all__ = [
    "QueryParser",
    "get_default_parser",
    "Retriever",
    "Responder",
    "CloudLLMConfig",
    "summarize_messages_local",
    "compare_contacts_local",
    "ner",
]
