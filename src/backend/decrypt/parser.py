"""解密后的微信数据库 → 应用数据模型解析器。

输入：已用 SQLCipher 解开的微信 db 连接（消息库 + 联系人库）
输出：应用内的 Contact / Message 列表，可直接写入本地库

不同微信版本的表结构差异：
- 微信 3.x：MSG*.db 里有 MSG 表，MicroMsg.db 里有 Contact 表
- 微信 4.0：message_*.db 里有 message / chat 表，contact_*.db 里有 contact 表
本解析器按 version.generation 切换 SQL。
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from ..storage.models import Contact, Message
from .adapter import WeChatGeneration, WeChatVersionInfo

# Zstandard 解压（用于 WCDB_CT_message_content=4 的压缩内容）
# pip install zstandard 可启用，未安装时回退显示原始 bytes
_zstd_decompress = None
try:
    import zstandard as _zstd
    _zstd_decompress = _zstd.ZstdDecompressor().decompress
except ImportError:
    pass


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
        # 微信 4.x contact 表实际结构（列名有差异）：
        #   id, username, local_type, alias, encrypt_username, flag, ...,
        #   nick_name (不是 nickname), remark, ...
        sql = """
            SELECT username, nick_name, remark, alias
            FROM contact
            WHERE username IS NOT NULL AND username != ''
        """
        try:
            cur = conn.execute(sql)
        except sqlite3.Error:
            # 兜底：尝试兼容列名
            try:
                cur = conn.execute("SELECT username, nick_name, remark, alias FROM contact")
            except sqlite3.Error:
                return
        for row in cur.fetchall():
            yield ParsedContact(
                wxid=row[0] or "",
                nickname=(row[1] or ""),
                remark=(row[2] or ""),
                alias=(row[3] or ""),
            )


# ----------------------------------------------------------------------------
# 消息解析
# ----------------------------------------------------------------------------
def _build_sender_map(conn: sqlite3.Connection) -> dict[int, str]:
    """从 Name2Id 表构建 sender_map: rowid → username。"""
    sender_map: dict[int, str] = {}
    try:
        for row in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            sender_map[row[0]] = row[1]
    except sqlite3.Error:
        pass
    return sender_map


def _build_hash_to_username(sender_map: dict[int, str]) -> dict[str, str]:
    """构建 hash → username 的映射（用于 Msg_<md5> 表名反查）。"""
    hash_to_username: dict[str, str] = {}
    for username in sender_map.values():
        if username:
            h = hashlib.md5(username.encode()).hexdigest()
            hash_to_username[h] = username
    return hash_to_username


def _find_msg_tables(conn: sqlite3.Connection) -> list[str]:
    """找出当前数据库中所有 Msg_* 消息表的名称。"""
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
        )
        return [row[0] for row in cur.fetchall()]
    except sqlite3.Error:
        return []


def iter_messages(
    conn: sqlite3.Connection,
    version: WeChatVersionInfo,
    batch_size: int = 1000,
    self_wxid: Optional[str] = None,
) -> Iterator[ParsedMessage]:
    """从消息库迭代产出 ParsedMessage。

    微信 4.x（4.0.3.80+）使用 Msg_<md5(username)> 格式的频道表，
    而非统一的 message 表。每个聊天（联系人/群）独立一张表。
    """
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
        # 微信 4.x 无统一 message 表，使用 Msg_<md5(username)> 频道表。
        # 每个 Msg_ 表代表一个聊天的全部消息。
        #
        # Msg_ 表结构：
        #   local_id, server_id, local_type, sort_seq, real_sender_id,
        #   create_time, status, ..., message_content, ...
        #
        # real_sender_id 映射到 Name2Id.rowid → user_name（即 wxid）。

        # 1. 构建 Name2Id 映射
        sender_map = _build_sender_map(conn)

        # 2. 构建 hash → username 映射（用于解析 Msg_<md5> 表名）
        hash_to_username = _build_hash_to_username(sender_map)

        # 3. 找出所有 Msg_* 表
        msg_tables = _find_msg_tables(conn)
        if not msg_tables:
            return

        for table_name in msg_tables:
            h = table_name[4:]  # 去掉 "Msg_" 前缀
            chat_username = hash_to_username.get(h, "")
            if not chat_username:
                continue  # 无法解析的聊天，跳过

            # 判断是否群聊
            is_group = chat_username.endswith("@chatroom") or chat_username.endswith("@openim")

            # 4. 读取该表消息
            try:
                cur = conn.execute(
                    f"SELECT local_id, server_id, local_type, sort_seq, real_sender_id,"
                    f" create_time, status, message_content, WCDB_CT_message_content"
                    f" FROM [{table_name}] ORDER BY sort_seq"
                )
            except sqlite3.Error:
                continue

            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                for row in rows:
                    try:
                        # 解析固定位置的字段
                        (_local_id, server_id, local_type, sort_seq,
                         real_sender_id, create_time, status,
                         raw_content, ct_flag) = tuple(row[:9])

                        # 解析 content：可能为 bytes 或 str，可能 zstd 压缩
                        message_content = ""
                        if raw_content is not None:
                            raw_bytes = raw_content if isinstance(raw_content, bytes) else str(raw_content).encode("utf-8")
                            try:
                                if ct_flag == 4 and _zstd_decompress is not None:
                                    message_content = _zstd_decompress(raw_bytes).decode("utf-8", errors="replace")
                                else:
                                    message_content = raw_bytes.decode("utf-8", errors="replace")
                            except Exception:
                                message_content = raw_bytes.decode("utf-8", errors="replace")

                        # 通过 Name2Id 解析发送者
                        sender_uname = sender_map.get(real_sender_id, "")

                        # 判断 is_self
                        if is_group:
                            is_self = bool(self_wxid and sender_uname == self_wxid)
                        else:
                            # 单聊：发送者是对方 → 收到的消息
                            is_self = (sender_uname != chat_username)

                        yield ParsedMessage(
                            msg_id=str(server_id),
                            talker_wxid=chat_username,
                            is_self=is_self,
                            sender=sender_uname if is_group else "",
                            msg_type_raw=int(local_type),
                            content=message_content,
                            created_ts=int(create_time or 0),
                        )
                    except (KeyError, IndexError, ValueError, TypeError):
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
def _find_sqlcipher_binary() -> Optional[str]:
    """查找可用的 sqlcipher 二进制。

    优先级：
    1. 随应用打包的 bin/<platform>/sqlcipher（打包态）
    2. 系统 PATH 中的 sqlcipher（开发态或用户已安装）
    """
    import shutil
    import sys

    # 1. 打包态：bin/<platform>/sqlcipher
    try:
        from ..config import get_bin_dir
        bin_dir = get_bin_dir()
        if sys.platform == "win32":
            candidates = [
                bin_dir / "windows" / "sqlcipher.exe",
                bin_dir / "win" / "sqlcipher.exe",
                bin_dir / "sqlcipher.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                bin_dir / "macos" / "sqlcipher",
                bin_dir / "mac" / "sqlcipher",
                bin_dir / "darwin" / "sqlcipher",
                bin_dir / "sqlcipher",
            ]
        else:
            candidates = [
                bin_dir / "linux" / "sqlcipher",
                bin_dir / "sqlcipher",
            ]
        for c in candidates:
            if c.exists() and c.is_file():
                # 确保有执行权限
                try:
                    import os as _os
                    _os.chmod(str(c), 0o755)
                except Exception:
                    pass
                return str(c)
    except Exception:
        pass

    # 2. 系统 PATH
    found = shutil.which("sqlcipher")
    if found:
        return found
    return None


def is_sqlcipher_available() -> bool:
    """检测 SQLCipher 解密能力是否可用。"""
    # 优先 pysqlcipher3（Python 原生，性能最好）
    try:
        from pysqlcipher3 import dbapi2  # noqa: F401
        return True
    except ImportError:
        pass
    # 检查打包的或系统的 sqlcipher CLI
    return _find_sqlcipher_binary() is not None


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

    优先用 pysqlcipher3（性能最好），回退到 sqlcipher CLI。
    打包态会自动查找随应用分发的 sqlcipher 二进制。
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

    # 回退：用 sqlcipher CLI（打包的或系统的）把加密库导出为明文临时库
    return _open_via_sqlcipher_cli(db_path, key, sqlcipher_compatibility)


class _WTAConnection(sqlite3.Connection):
    """sqlite3.Connection 子类，支持存储 _wta_tmp_path 等临时属性。

    sqlite3.Connection 是 C 类型，不支持任意属性赋值。
    某些环境下（如打包的 pysqlcipher3 替代库）可能会尝试在连接上设置
    _wta_tmp_path 等属性，使用本子类可避免 AttributeError。
    """
    _wta_tmp_path: str = ""


def _open_via_sqlcipher_cli(
    db_path,
    key: bytes,
    sqlcipher_compatibility: int,
) -> sqlite3.Connection:
    """用 sqlcipher CLI 解密数据库到临时文件，再用 sqlite3 打开。

    优先用随应用打包的 sqlcipher 二进制，其次系统 PATH。
    """
    import os
    import tempfile

    sqlcipher_bin = _find_sqlcipher_binary()
    if sqlcipher_bin is None:
        raise RuntimeError(
            "未安装 pysqlcipher3，且未找到 sqlcipher 二进制（打包态或系统均无），"
            "无法解密微信数据库。\n"
            "解决方案：\n"
            "1. 重新打包（构建脚本会自动下载 sqlcipher 二进制到 bin/）\n"
            "2. 或手动安装：macOS 执行 brew install sqlcipher；"
            "Windows 从 https://github.com/sqlcipher/sqlcipher/releases 下载\n"
            "3. 或执行 pip install pysqlcipher3"
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

    # 使用支持属性赋值的连接子类，避免某些环境尝试设置 _wta_tmp_path 时报错
    conn = sqlite3.connect(tmp_path, factory=_WTAConnection)
    conn._wta_tmp_path = tmp_path
    conn.row_factory = sqlite3.Row
    # 用 atexit 注册临时文件清理
    import atexit
    atexit.register(_cleanup_tmp_db, tmp_path)
    return conn


def _cleanup_tmp_db(tmp_path: str) -> None:
    """进程退出时清理 sqlcipher CLI 导出的临时明文库。"""
    try:
        p = Path(tmp_path)
        if p.exists():
            p.unlink()
    except Exception:
        pass
