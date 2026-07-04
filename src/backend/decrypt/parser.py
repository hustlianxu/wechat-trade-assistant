"""解密后的微信数据库 → 应用数据模型解析器。

输入：已用 SQLCipher 解开的微信 db 连接（消息库 + 联系人库）
输出：应用内的 Contact / Message 列表，可直接写入本地库

不同微信版本的表结构差异：
- 微信 3.x：MSG*.db 里有 MSG 表，MicroMsg.db 里有 Contact 表
- 微信 4.0：message_*.db 里有 message / chat 表，contact_*.db 里有 contact 表
本解析器按 version.generation 切换 SQL。
"""

from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from ..storage.models import Contact, Message
from .adapter import WeChatGeneration, WeChatVersionInfo


# ----------------------------------------------------------------------------
# 消息类型常量（微信原始 Type 值 → 我们简化的字符串）
# ----------------------------------------------------------------------------
MSG_TYPE_MAP = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    48: "location",
    49: "file",
    10000: "system",
    10002: "system",
}


def _map_msg_type(raw_type: int) -> str:
    return MSG_TYPE_MAP.get(raw_type, "other")


@dataclass
class ParsedContact:
    """从微信 DB 解析出的联系人原始数据。"""

    wxid: str
    nickname: str = ""
    remark: str = ""
    alias: str = ""
    region: str = ""


@dataclass
class ParsedMessage:
    """从微信 DB 解析出的消息原始数据。"""

    msg_id: str
    talker_wxid: str  # 对话对方的 wxid
    is_self: bool
    sender: str  # 群聊里的发送者 wxid，单聊为空
    msg_type_raw: int
    content: str
    created_ts: int
    raw_path: str = ""  # 语音/图片的原始路径


# ----------------------------------------------------------------------------
# 联系人解析
# ----------------------------------------------------------------------------
def iter_contacts(
    conn: sqlite3.Connection,
    version: WeChatVersionInfo,
) -> Iterator[ParsedContact]:
    """从联系人库迭代产出 ParsedContact。"""
    if version.generation == WeChatGeneration.GEN_3:
        sql = """
            SELECT userName, nickName, remark, alias, conRemark, region
            FROM contact
            WHERE userName IS NOT NULL
        """
        try:
            cur = conn.execute(sql)
        except sqlite3.Error:
            # 部分 3.x 版本表结构不同
            cur = conn.execute("SELECT userName, nickName, remark, alias FROM contact")
        for row in cur.fetchall():
            yield ParsedContact(
                wxid=row["userName"] if "userName" in row.keys() else row[0],
                nickname=row["nickName"] if "nickName" in row.keys() else row[1],
                remark=row["conRemark"] if "conRemark" in row.keys() else (row[2] or ""),
                alias=row["alias"] if "alias" in row.keys() else row[3],
            )
    elif version.generation == WeChatGeneration.GEN_4:
        # 4.0 contact 表结构
        sql = """
            SELECT username, nickname, remark, alias, region
            FROM contact
        """
        try:
            cur = conn.execute(sql)
        except sqlite3.Error:
            return
        for row in cur.fetchall():
            yield ParsedContact(
                wxid=row[0] or "",
                nickname=row[1] or "",
                remark=row[2] or "",
                alias=row[3] or "",
                region=row[4] or "",
            )


# ----------------------------------------------------------------------------
# 消息解析
# ----------------------------------------------------------------------------
def iter_messages(
    conn: sqlite3.Connection,
    version: WeChatVersionInfo,
    batch_size: int = 1000,
) -> Iterator[ParsedMessage]:
    """从消息库迭代产出 ParsedMessage。"""
    if version.generation == WeChatGeneration.GEN_3:
        sql = """
            SELECT TalkerId, MesSvrID, Type, SubType, StrContent, StrTalker,
                   CreateTime, IsSender, ExtraBuff
            FROM MSG
            WHERE MesSvrID IS NOT NULL AND MesSvrID != ''
            ORDER BY CreateTime ASC
        """
        try:
            cur = conn.execute(sql)
        except sqlite3.Error:
            # 表名可能是 MSG0/MSG1 ...
            try:
                cur = conn.execute(
                    "SELECT TalkerId, MesSvrID, Type, StrContent, StrTalker, CreateTime, IsSender FROM MSG0 ORDER BY CreateTime ASC"
                )
            except sqlite3.Error:
                return

        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                return
            for row in rows:
                try:
                    yield ParsedMessage(
                        msg_id=str(row["MesSvrID"]),
                        talker_wxid=row["StrTalker"],
                        is_self=bool(row["IsSender"]),
                        sender="",
                        msg_type_raw=int(row["Type"]),
                        content=row["StrContent"] or "",
                        created_ts=int(row["CreateTime"] or 0),
                    )
                except (KeyError, IndexError, ValueError):
                    continue

    elif version.generation == WeChatGeneration.GEN_4:
        sql = """
            SELECT rowid, talker_id, message_id, type, content, create_time, is_self, sender_id
            FROM message
            ORDER BY create_time ASC
        """
        try:
            cur = conn.execute(sql)
        except sqlite3.Error:
            return
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                return
            for row in rows:
                try:
                    yield ParsedMessage(
                        msg_id=str(row["message_id"]),
                        talker_wxid=row["talker_id"],
                        is_self=bool(row["is_self"]),
                        sender=row["sender_id"] or "",
                        msg_type_raw=int(row["type"]),
                        content=row["content"] or "",
                        created_ts=int(row["create_time"] or 0),
                    )
                except (KeyError, IndexError, ValueError):
                    continue


# ----------------------------------------------------------------------------
# 转换为应用模型
# ----------------------------------------------------------------------------
def to_contact_model(parsed: ParsedContact) -> Contact:
    """转成 storage.Contact 模型。"""
    return Contact(
        wxid=parsed.wxid,
        nickname=parsed.nickname,
        remark=parsed.remark,
        alias=parsed.alias,
        region=parsed.region,
    )


def to_message_model(parsed: ParsedMessage, contact_id: int) -> Message:
    """转成 storage.Message 模型。

    注意：msg_id 为空时会生成 fallback ID，避免唯一约束失败。
    """
    msg_id = parsed.msg_id or f"{parsed.talker_wxid}-{parsed.created_ts}-{parsed.msg_type_raw}"
    return Message(
        contact_id=contact_id,
        msg_id=msg_id,
        msg_type=_map_msg_type(parsed.msg_type_raw),
        direction="out" if parsed.is_self else "in",
        sender=parsed.sender,
        content=parsed.content,
        raw_path=parsed.raw_path,
        created_ts=parsed.created_ts,
    )


# ----------------------------------------------------------------------------
# 打开解密连接
# ----------------------------------------------------------------------------
def is_sqlcipher_available() -> bool:
    """检测 SQLCipher 解密能力是否可用。"""
    try:
        from pysqlcipher3 import dbapi2  # noqa: F401
        return True
    except ImportError:
        pass
    # 检查 sqlcipher CLI
    import shutil
    return shutil.which("sqlcipher") is not None


def open_decrypted_db(
    db_path,
    key: bytes,
    sqlcipher_compatibility: int = 4,
) -> sqlite3.Connection:
    """打开解密后的微信数据库连接。

    Args:
        db_path: 数据库文件路径
        key: 32 字节密钥
        sqlcipher_compatibility: 3 或 4

    需要 pysqlcipher3 或系统 sqlcipher CLI。沙箱环境若都不可用会抛 RuntimeError。
    """
    # 优先 pysqlcipher3（Python 原生连接，性能最好）
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore
    except ImportError:
        sqlcipher = None

    if sqlcipher is not None:
        conn = sqlcipher.connect(str(db_path))
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\";")
        conn.execute(f"PRAGMA cipher_compatibility = {sqlcipher_compatibility};")
        # 验证可读
        try:
            conn.execute("SELECT count(*) FROM sqlite_master")
        except Exception as e:  # noqa: BLE001
            conn.close()
            raise RuntimeError(f"密钥错误或数据库版本不匹配：{e}") from e
        conn.row_factory = sqlite3.Row
        return conn

    # 回退：用系统 sqlcipher CLI 把加密库导出为明文临时库
    return _open_via_sqlcipher_cli(db_path, key, sqlcipher_compatibility)


def _open_via_sqlcipher_cli(
    db_path,
    key: bytes,
    sqlcipher_compatibility: int,
) -> sqlite3.Connection:
    """用 sqlcipher CLI 解密数据库到临时文件，再用 sqlite3 打开。

    适用于没有 pysqlcipher3 但系统装了 sqlcipher 的环境。
    """
    import os
    import shutil
    import tempfile

    sqlcipher_bin = shutil.which("sqlcipher")
    if sqlcipher_bin is None:
        raise RuntimeError(
            "未安装 pysqlcipher3，且系统无 sqlcipher 命令，无法解密微信数据库。"
            "请执行 pip install pysqlcipher3，或安装 sqlcipher（macOS: brew install sqlcipher）。"
        )

    # 用 sqlcipher CLI 导出明文库
    fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="wta_dec_")
    os.close(fd)
    os.unlink(tmp_path)  # sqlcipher 需要目标不存在

    sql = (
        f"PRAGMA key = \"x'{key.hex()}'\";\n"
        f"PRAGMA cipher_compatibility = {sqlcipher_compatibility};\n"
        f"ATTACH DATABASE '{tmp_path}' AS plaintext KEY '';\n"
        f"SELECT sqlcipher_export('plaintext');\n"
        f"DETACH DATABASE plaintext;\n"
    )
    result = subprocess.run(
        [sqlcipher_bin, str(db_path)],
        input=sql,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0 or not Path(tmp_path).exists():
        raise RuntimeError(
            f"sqlcipher CLI 解密失败：{result.stderr[:500] or result.stdout[:500]}"
        )

    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    # 标记临时库路径，关闭时清理
    conn._wta_tmp_path = tmp_path  # type: ignore[attr-defined]
    return conn
