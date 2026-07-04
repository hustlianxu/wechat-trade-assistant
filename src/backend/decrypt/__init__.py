"""解密引擎模块（基于 wechat-decrypt）。

对外暴露：
- adapter：版本检测与路径定位
- extractor：密钥提取（memory/registry/manual）
- parser：解密后的微信 DB → 应用数据模型
- image_decoder：图片 .dat 解密（V1/V2/wxgf）
- sse_listener：实时消息监听
- macos_helper：macOS 重签名助手

完整流水线：
    version = detect_installed_wechat()
    key = extract_key(version, source="auto")
    msg_conn = open_decrypted_db(msg_db_path, key.key_bytes, version.sqlcipher_compatibility)
    for parsed in iter_messages(msg_conn, version):
        ...
"""

from . import adapter, image_decoder, macos_helper, parser
from .adapter import (
    Platform,
    WeChatGeneration,
    WeChatVersionInfo,
    detect_installed_wechat,
    find_micro_msg_db,
    find_msg_db,
    find_wechat_data_dirs,
    parse_version,
)
from .extractor import (
    ExtractedKey,
    KeyExtractionError,
    extract_key,
    make_manual_key,
    validate_manual_key,
)
from .image_decoder import decrypt_dat_image
from .macos_helper import (
    ResignResult,
    find_wechat_app,
    is_resigned,
    needs_resign,
    perform_resign,
)
from .parser import (
    ParsedContact,
    ParsedMessage,
    iter_contacts,
    iter_messages,
    open_decrypted_db,
    to_contact_model,
    to_message_model,
)
from .sse_listener import PollingListener, SSEConfig

__all__ = [
    # adapter
    "Platform",
    "WeChatGeneration",
    "WeChatVersionInfo",
    "detect_installed_wechat",
    "find_wechat_data_dirs",
    "find_msg_db",
    "find_micro_msg_db",
    "parse_version",
    "adapter",
    # extractor
    "ExtractedKey",
    "KeyExtractionError",
    "extract_key",
    "make_manual_key",
    "validate_manual_key",
    # parser
    "ParsedContact",
    "ParsedMessage",
    "iter_contacts",
    "iter_messages",
    "open_decrypted_db",
    "to_contact_model",
    "to_message_model",
    "parser",
    # image
    "decrypt_dat_image",
    "image_decoder",
    # sse
    "PollingListener",
    "SSEConfig",
    # macos
    "ResignResult",
    "find_wechat_app",
    "is_resigned",
    "needs_resign",
    "perform_resign",
    "macos_helper",
]
