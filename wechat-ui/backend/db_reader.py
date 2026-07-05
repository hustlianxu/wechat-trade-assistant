"""读取 wechat-decrypt 解密后的 SQLite 数据库。

核心数据流：
  decrypted/
  ├── contact/contact.db          → contact 表（username, nick_name, remark, alias, local_type）
  ├── session/session.db          → SessionTable（username, summary, last_timestamp）
  ├── message/message_0.db ~ N    → Name2Id + Msg_<md5(username)> 表
  ├── message/media_0.db ~ N      → VoiceInfo 表（voice_data BLOB）
  └── message/message_resource.db → MessageResourceInfo（图片 MD5）

消息表名规则：Msg_<md5(username)>
消息类型：local_type 是复合编码 (sub_type << 32) | base_type，取低 32 位为基础类型
  1=文本, 3=图片, 34=语音, 43=视频, 49=链接/文件, 10000=系统, 10002=撤回
群聊：username 以 @chatroom 结尾
自己发送：real_sender_id 对应的 Name2Id.user_name == self_wxid
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


# ============================================================================
# 消息类型常量
# ============================================================================
MSG_TYPE_TEXT = 1
MSG_TYPE_IMAGE = 3
MSG_TYPE_VOICE = 34
MSG_TYPE_CONTACT_CARD = 42
MSG_TYPE_VIDEO = 43
MSG_TYPE_EMOJI = 47
MSG_TYPE_LOCATION = 48
MSG_TYPE_LINK = 49
MSG_TYPE_VOIP = 50
MSG_TYPE_SYSTEM = 10000
MSG_TYPE_RECALL = 10002

MSG_TYPE_NAMES = {
    1: "文本", 3: "图片", 34: "语音", 42: "名片", 43: "视频",
    47: "表情", 48: "位置", 49: "链接/文件", 50: "通话",
    10000: "系统", 10002: "撤回",
}


def split_msg_type(local_type: int) -> tuple[int, int]:
    """拆分复合消息类型：返回 (base_type, sub_type)。"""
    if local_type > 0xFFFFFFFF:
        return local_type & 0xFFFFFFFF, local_type >> 32
    return local_type, 0


def msg_type_name(local_type: int) -> str:
    base, _ = split_msg_type(local_type)
    return MSG_TYPE_NAMES.get(base, f"未知({base})")


# ============================================================================
# 数据类
# ============================================================================
@dataclass
class Contact:
    username: str
    nickname: str = ""
    remark: str = ""
    alias: str = ""
    description: str = ""
    phone: str = ""
    # 最后消息时间戳（来自 SessionTable，0 表示无会话记录）
    last_msg_ts: int = 0
    last_msg_summary: str = ""
    last_msg_type: int = 0
    unread_count: int = 0

    @property
    def display_name(self) -> str:
        """显示名优先级：备注 > 昵称 > wxid。"""
        return self.remark or self.nickname or self.username

    @property
    def is_group(self) -> bool:
        return self.username.endswith("@chatroom")

    @property
    def is_official(self) -> bool:
        """公众号。"""
        return self.username.startswith("gh_")


@dataclass
class Message:
    local_id: int
    server_id: int
    local_type: int
    create_time: int
    real_sender_id: int
    sender_wxid: str = ""
    content: str = ""
    is_self: bool = False
    # 语音转录文本（异步填充）
    transcription: str = ""
    # 图片/文件 URL（异步填充）
    media_url: str = ""

    @property
    def base_type(self) -> int:
        base, _ = split_msg_type(self.local_type)
        return base

    @property
    def type_name(self) -> str:
        return msg_type_name(self.local_type)

    @property
    def is_text(self) -> bool:
        return self.base_type == MSG_TYPE_TEXT

    @property
    def is_voice(self) -> bool:
        return self.base_type == MSG_TYPE_VOICE

    @property
    def is_image(self) -> bool:
        return self.base_type == MSG_TYPE_IMAGE

    @property
    def is_video(self) -> bool:
        return self.base_type == MSG_TYPE_VIDEO

    @property
    def is_link(self) -> bool:
        return self.base_type == MSG_TYPE_LINK

    @property
    def is_system(self) -> bool:
        return self.base_type in (MSG_TYPE_SYSTEM, MSG_TYPE_RECALL)


# ============================================================================
# 数据库读取器
# ============================================================================
class DbReader:
    """读取解密后的微信数据库。

    使用方式：
        reader = DbReader("/path/to/decrypted")
        contacts = reader.list_contacts()
        messages = reader.list_messages("wxid_xxx", limit=100)
    """

    def __init__(self, decrypted_dir: str | Path):
        self.base = Path(decrypted_dir)
        if not self.base.exists():
            raise FileNotFoundError(f"解密目录不存在：{self.base}")

        # 数据库文件路径
        self.contact_db = self._find_db("contact/contact.db", "Contact/wccontact_new2.db")
        self.session_db = self._find_db("session/session.db", "Session/session_new.db")
        self.message_dbs = sorted(self.base.rglob("message_*.db"))
        # 排除 fts 和 resource 和 media
        self.message_dbs = [
            p for p in self.message_dbs
            if "fts" not in p.name and "resource" not in p.name and "media" not in p.name and "biz" not in p.name
        ]
        self.media_dbs = sorted(self.base.rglob("media_*.db"))
        self.resource_db = self._find_db("message/message_resource.db", "Message/message_resource.db")

        # 缓存：Name2Id 映射（每个 message_db 独立维护）
        self._name2id_cache: dict[str, dict[int, str]] = {}

    def _find_db(self, *relative_paths: str) -> Optional[Path]:
        """在解密目录下查找数据库文件，支持多种路径形式（4.x 小写 / 3.x 大写）。"""
        for rel in relative_paths:
            p = self.base / rel
            if p.exists():
                return p
        # 大小写不敏感搜索
        for rel in relative_paths:
            parts = rel.split("/")
            current = self.base
            for part in parts:
                found = None
                if current.is_dir():
                    for item in current.iterdir():
                        if item.name.lower() == part.lower():
                            found = item
                            break
                if found is None:
                    current = None
                    break
                current = found
            if current is not None and current.exists():
                return current
        return None

    def _connect(self, db_path: Optional[Path]) -> sqlite3.Connection:
        if db_path is None or not db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在")
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------------
    # 联系人 / 会话列表
    # ------------------------------------------------------------------------
    def list_contacts(
        self,
        contact_type: str = "all",
        sort: str = "recent",
        self_wxid: str = "",
    ) -> list[Contact]:
        """列出联系人/群聊/最近会话。

        Args:
            contact_type: "friends" | "groups" | "recent" | "all"
            sort: "recent"（按最后消息时间倒序）| "name"（按显示名排序）
            self_wxid: 本账号 wxid，用于过滤自己
        """
        # 1. 从 contact.db 加载所有联系人
        contacts_map: dict[str, Contact] = {}
        if self.contact_db:
            try:
                conn = self._connect(self.contact_db)
                # 动态获取列名（不同版本字段名可能不同）
                cols = {row["name"].lower() for row in conn.execute("PRAGMA table_info(contact)").fetchall()}
                username_col = "username" if "username" in cols else "userName"
                nick_col = "nick_name" if "nick_name" in cols else ("nickname" if "nickname" in cols else "nickName")
                remark_col = "remark" if "remark" in cols else "conRemark"
                alias_col = "alias" if "alias" in cols else "alias"
                desc_col = "description" if "description" in cols else "description"
                phone_col = None
                for c in ("phone", "phone_number", "mobile", "mobile_phone", "telephone"):
                    if c in cols:
                        phone_col = c
                        break

                sql = f"SELECT {username_col}, {nick_col}, {remark_col}, {alias_col}"
                if desc_col in cols:
                    sql += f", {desc_col}"
                if phone_col:
                    sql += f", {phone_col}"
                # 过滤群成员（local_type=3 会导致数量爆炸）
                if "local_type" in cols:
                    sql += " FROM contact WHERE local_type != 3"
                else:
                    sql += " FROM contact"

                for row in conn.execute(sql).fetchall():
                    username = row[0] or ""
                    if not username or (self_wxid and username == self_wxid):
                        continue
                    c = Contact(
                        username=username,
                        nickname=row[1] or "",
                        remark=row[2] or "",
                        alias=row[3] or "",
                        description=row[4] if len(row.keys()) > 4 and desc_col in cols else "",
                        phone=row[5] if phone_col and len(row.keys()) > 5 else "",
                    )
                    contacts_map[username] = c
                conn.close()
            except sqlite3.Error:
                pass

        # 2. 从 session.db 补充最后消息信息
        if self.session_db:
            try:
                conn = self._connect(self.session_db)
                for row in conn.execute("""
                    SELECT username, summary, last_timestamp, last_msg_type, unread_count
                    FROM SessionTable
                    WHERE last_timestamp > 0
                """).fetchall():
                    username = row["username"] or ""
                    if not username:
                        continue
                    if username not in contacts_map:
                        contacts_map[username] = Contact(username=username)
                    c = contacts_map[username]
                    c.last_msg_ts = row["last_timestamp"] or 0
                    summary = row["summary"]
                    # summary 可能是 zstd 压缩的 bytes
                    if isinstance(summary, bytes):
                        summary = _decompress_zstd(summary)
                    if isinstance(summary, str) and ":\n" in summary:
                        # 群消息前缀 wxid_xxx:\n
                        summary = summary.split(":\n", 1)[-1]
                    c.last_msg_summary = summary or ""
                    c.last_msg_type = row["last_msg_type"] or 0
                    c.unread_count = row["unread_count"] or 0
                conn.close()
            except sqlite3.Error:
                pass

        # 3. 按类型过滤
        contacts = list(contacts_map.values())
        if contact_type == "friends":
            contacts = [c for c in contacts if not c.is_group and not c.is_official]
        elif contact_type == "groups":
            contacts = [c for c in contacts if c.is_group]
        elif contact_type == "recent":
            # 最近：只显示有消息记录的，按时间倒序
            contacts = [c for c in contacts if c.last_msg_ts > 0]
            contacts.sort(key=lambda c: c.last_msg_ts, reverse=True)
            return contacts
        elif contact_type == "all":
            pass

        # 4. 排序
        if sort == "name":
            contacts.sort(key=lambda c: c.display_name.lower())
        else:  # recent
            contacts.sort(key=lambda c: c.last_msg_ts, reverse=True)

        return contacts

    def get_contact(self, username: str) -> Optional[Contact]:
        """获取单个联系人信息。"""
        contacts = self.list_contacts(contact_type="all")
        for c in contacts:
            if c.username == username:
                return c
        return None

    # ------------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------------
    def _get_name2id_map(self, db_path: Path) -> dict[int, str]:
        """获取某个 message_db 的 Name2Id 映射（带缓存）。"""
        cache_key = str(db_path)
        if cache_key in self._name2id_cache:
            return self._name2id_cache[cache_key]

        mapping: dict[int, str] = {}
        try:
            conn = self._connect(db_path)
            for row in conn.execute("SELECT rowid, user_name FROM Name2Id").fetchall():
                mapping[row[0]] = row[1] or ""
            conn.close()
        except sqlite3.Error:
            pass

        self._name2id_cache[cache_key] = mapping
        return mapping

    def _msg_table_name(self, username: str) -> str:
        """消息表名：Msg_<md5(username)>。"""
        return f"Msg_{hashlib.md5(username.encode()).hexdigest()}"

    def list_messages(
        self,
        username: str,
        self_wxid: str = "",
        start_ts: int = 0,
        end_ts: int = 0,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Message]:
        """列出某个会话的消息（按时间正序）。

        会遍历所有 message_N.db 分片，因为同一个 username 的消息可能分散在多个分片中。
        """
        table = self._msg_table_name(username)
        all_messages: list[Message] = []

        for db_path in self.message_dbs:
            # 先检查这个分片里有没有该表
            try:
                conn = self._connect(db_path)
                # 检查表是否存在
                exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if not exists:
                    conn.close()
                    continue

                name2id = self._get_name2id_map(db_path)

                sql = f"""
                    SELECT local_id, server_id, local_type, create_time,
                           real_sender_id, message_content, WCDB_CT_message_content
                    FROM "{table}"
                    WHERE 1=1
                """
                params: list = []
                if start_ts > 0:
                    sql += " AND create_time >= ?"
                    params.append(start_ts)
                if end_ts > 0:
                    sql += " AND create_time <= ?"
                    params.append(end_ts)
                sql += " ORDER BY create_time ASC"

                for row in conn.execute(sql, params).fetchall():
                    content = row["message_content"]
                    ct = row["WCDB_CT_message_content"] if "WCDB_CT_message_content" in row.keys() else 0
                    # 解压 zstd
                    if ct == 4 and isinstance(content, bytes):
                        content = _decompress_zstd(content)
                    if isinstance(content, bytes):
                        content = content.decode("utf-8", errors="replace")

                    # 群消息前缀剥离
                    if username.endswith("@chatroom") and content:
                        if ":\n" in content:
                            content = content.split(":\n", 1)[-1]
                        else:
                            # 无换行的前缀（如 XML）
                            import re
                            m = re.match(r'^([A-Za-z0-9_\-@.]+):(<\?xml|<msg)', content)
                            if m:
                                content = content[len(m.group(1)) + 1:]

                    sender_wxid = name2id.get(row["real_sender_id"], "")
                    is_self = bool(self_wxid and sender_wxid == self_wxid)

                    msg = Message(
                        local_id=row["local_id"],
                        server_id=row["server_id"] or 0,
                        local_type=row["local_type"],
                        create_time=row["create_time"] or 0,
                        real_sender_id=row["real_sender_id"],
                        sender_wxid=sender_wxid,
                        content=content or "",
                        is_self=is_self,
                    )
                    all_messages.append(msg)
                conn.close()
            except sqlite3.Error:
                continue

        # 合并后排序（多个分片可能时间交叉）
        all_messages.sort(key=lambda m: m.create_time)

        # 分页
        if offset > 0:
            all_messages = all_messages[offset:]
        if limit > 0:
            all_messages = all_messages[:limit]

        return all_messages

    def search_messages(
        self,
        keyword: str,
        username: str = "",
        limit: int = 100,
    ) -> list[Message]:
        """搜索消息（关键词匹配）。"""
        results: list[Message] = []
        table = self._msg_table_name(username) if username else None

        for db_path in self.message_dbs:
            try:
                conn = self._connect(db_path)
                name2id = self._get_name2id_map(db_path)

                if table:
                    # 搜索特定会话
                    exists = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not exists:
                        conn.close()
                        continue
                    sql = f"""
                        SELECT local_id, server_id, local_type, create_time,
                               real_sender_id, message_content, WCDB_CT_message_content
                        FROM "{table}"
                        WHERE message_content LIKE ?
                        ORDER BY create_time DESC LIMIT ?
                    """
                    rows = conn.execute(sql, (f"%{keyword}%", limit)).fetchall()
                else:
                    # 搜索所有表
                    tables = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"
                    ).fetchall()
                    rows = []
                    for t in tables:
                        try:
                            rows.extend(conn.execute(
                                f'SELECT local_id, server_id, local_type, create_time, '
                                f'real_sender_id, message_content, WCDB_CT_message_content '
                                f'FROM "{t[0]}" WHERE message_content LIKE ? '
                                f'ORDER BY create_time DESC LIMIT ?',
                                (f"%{keyword}%", limit),
                            ).fetchall())
                        except sqlite3.Error:
                            continue

                for row in rows:
                    content = row["message_content"]
                    ct = row["WCDB_CT_message_content"] if "WCDB_CT_message_content" in row.keys() else 0
                    if ct == 4 and isinstance(content, bytes):
                        content = _decompress_zstd(content)
                    if isinstance(content, bytes):
                        content = content.decode("utf-8", errors="replace")

                    sender_wxid = name2id.get(row["real_sender_id"], "")
                    results.append(Message(
                        local_id=row["local_id"],
                        server_id=row["server_id"] or 0,
                        local_type=row["local_type"],
                        create_time=row["create_time"],
                        real_sender_id=row["real_sender_id"],
                        sender_wxid=sender_wxid,
                        content=content or "",
                    ))

                conn.close()
            except sqlite3.Error:
                continue

        results.sort(key=lambda m: m.create_time, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------------
    # 语音数据
    # ------------------------------------------------------------------------
    def get_voice_data(self, username: str, local_id: int) -> Optional[bytes]:
        """获取语音消息的 SILK 原始数据。

        遍历所有 media_*.db，通过 (username, local_id) 定位 VoiceInfo.voice_data。
        """
        for db_path in self.media_dbs:
            try:
                conn = self._connect(db_path)
                # 查 chat_name_id
                row = conn.execute(
                    "SELECT rowid FROM Name2Id WHERE user_name = ?", (username,)
                ).fetchone()
                if row is None:
                    conn.close()
                    continue
                chat_name_id = row[0]

                voice_row = conn.execute(
                    "SELECT voice_data FROM VoiceInfo WHERE chat_name_id = ? AND local_id = ?",
                    (chat_name_id, local_id),
                ).fetchone()
                conn.close()
                if voice_row and voice_row[0]:
                    data = voice_row[0]
                    # SILK 头：首字节 0x02 需剥离
                    if data[0:1] == b"\x02":
                        return data[1:]
                    return data
            except sqlite3.Error:
                continue
        return None


# ============================================================================
# 工具函数
# ============================================================================
def _decompress_zstd(data: bytes) -> str:
    """解压 zstd 压缩的数据。优先用 zstandard 库，回退到 zlib。"""
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(data).decode("utf-8", errors="replace")
    except ImportError:
        pass
    try:
        return zlib.decompress(data).decode("utf-8", errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")
