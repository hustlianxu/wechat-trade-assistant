"""数据访问层（Repository）。

封装所有对 SQLite 的读写，对上层模块暴露领域方法。
所有方法都接收 db: Database，便于测试时注入临时库。
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .db import Database
from .models import (
    AssistantTurn,
    Contact,
    Message,
    QueryFilter,
    Todo,
)


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def _now() -> int:
    return int(time.time())


def _row_to_contact(row: sqlite3.Row) -> Contact:
    return Contact(
        id=row["id"],
        wxid=row["wxid"],
        nickname=row["nickname"],
        remark=row["remark"],
        alias=row["alias"],
        region=row["region"],
        last_intent=row["last_intent"],
        last_intent_ts=row["last_intent_ts"],
        last_msg_ts=row["last_msg_ts"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        contact_id=row["contact_id"],
        msg_id=row["msg_id"],
        msg_type=row["msg_type"],
        direction=row["direction"],
        sender=row["sender"],
        content=row["content"],
        raw_path=row["raw_path"],
        thumb_path=row["thumb_path"],
        transcribed=bool(row["transcribed"]),
        intent=row["intent"],
        confidence=row["confidence"],
        created_ts=row["created_ts"],
        ingested_ts=row["ingested_ts"],
    )


def _row_to_todo(row: sqlite3.Row) -> Todo:
    return Todo(
        id=row["id"],
        contact_id=row["contact_id"],
        message_id=row["message_id"],
        title=row["title"],
        detail=row["detail"],
        due_ts=row["due_ts"],
        status=row["status"],
        source=row["source"],
        priority=row["priority"],
        created_ts=row["created_ts"],
        updated_ts=row["updated_ts"],
        completed_ts=row["completed_ts"],
    )


# ============================================================================
# Repository
# ============================================================================
class Repository:
    """所有持久化操作的统一入口。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------------
    # 客户
    # ------------------------------------------------------------------------
    def upsert_contact(self, contact: Contact) -> int:
        """新增或更新客户（按 wxid 唯一）。返回主键 id。"""
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO contacts (wxid, nickname, remark, alias, region, note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wxid) DO UPDATE SET
                    nickname=excluded.nickname,
                    remark=excluded.remark,
                    alias=excluded.alias,
                    region=excluded.region,
                    note=excluded.note,
                    updated_at=strftime('%s','now')
                RETURNING id
                """,
                (
                    contact.wxid,
                    contact.nickname,
                    contact.remark,
                    contact.alias,
                    contact.region,
                    contact.note,
                    _now(),
                ),
            )
            row = cur.fetchone()
            return row["id"]

    def list_contacts(
        self,
        intent: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Contact]:
        conn = self.db.connect()
        if intent:
            cur = conn.execute(
                "SELECT * FROM contacts WHERE last_intent = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (intent, limit, offset),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM contacts ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [_row_to_contact(r) for r in cur.fetchall()]

    def count_contacts(self, intent: Optional[str] = None) -> int:
        conn = self.db.connect()
        if intent:
            cur = conn.execute(
                "SELECT COUNT(*) FROM contacts WHERE last_intent = ?",
                (intent,),
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM contacts")
        row = cur.fetchone()
        return row[0] if row else 0

    def get_contact(self, contact_id: int) -> Optional[Contact]:
        conn = self.db.connect()
        cur = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        row = cur.fetchone()
        return _row_to_contact(row) if row else None

    def get_latest_message_ts(self) -> int:
        """返回本地库中最大的 created_ts（秒），无消息时返回 0。"""
        row = self.db.execute(
            "SELECT MAX(created_ts) AS m FROM messages"
        ).fetchone()
        if row is None or row["m"] is None:
            return 0
        return int(row["m"])

    def get_contact_id_by_wxid(self, wxid: str) -> Optional[int]:
        """按 wxid 查询客户主键 id，不存在返回 None。"""
        conn = self.db.connect()
        cur = conn.execute("SELECT id FROM contacts WHERE wxid = ?", (wxid,))
        row = cur.fetchone()
        return row["id"] if row else None

    def find_contacts_by_keyword(self, keyword: str) -> List[Contact]:
        """按昵称/备注/别名模糊匹配。"""
        conn = self.db.connect()
        like = f"%{keyword}%"
        cur = conn.execute(
            """
            SELECT * FROM contacts
            WHERE nickname LIKE ? OR remark LIKE ? OR alias LIKE ? OR wxid LIKE ?
            ORDER BY updated_at DESC
            """,
            (like, like, like, like),
        )
        return [_row_to_contact(r) for r in cur.fetchall()]

    def update_contact_intent(self, contact_id: int, intent: str, ts: Optional[int] = None) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE contacts
                SET last_intent = ?, last_intent_ts = ?, updated_at = ?
                WHERE id = ?
                """,
                (intent, ts or _now(), _now(), contact_id),
            )

    # ------------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------------
    def insert_message(self, msg: Message) -> int:
        """新增消息。若 msg_id 已存在则忽略（去重）。返回主键 id。"""
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages
                  (contact_id, msg_id, msg_type, direction, sender, content,
                   raw_path, thumb_path, transcribed, intent, confidence, created_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(msg_id) DO NOTHING
                RETURNING id
                """,
                (
                    msg.contact_id,
                    msg.msg_id,
                    msg.msg_type,
                    msg.direction,
                    msg.sender,
                    msg.content,
                    msg.raw_path,
                    msg.thumb_path,
                    int(msg.transcribed),
                    msg.intent,
                    msg.confidence,
                    msg.created_ts,
                ),
            )
            row = cur.fetchone()
            if row is None:
                # 已存在，查询现有 id 返回
                cur2 = conn.execute("SELECT id FROM messages WHERE msg_id = ?", (msg.msg_id,))
                row = cur2.fetchone()
                return row["id"] if row else 0
            msg_id_pk = row["id"]

            # 同步 FTS 索引（仅文本）
            if msg.content:
                conn.execute(
                    "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
                    (msg_id_pk, msg.content),
                )
            return msg_id_pk

    def insert_messages_bulk(self, msgs: Iterable[Message]) -> int:
        """批量插入消息，返回成功插入的条数。"""
        count = 0
        with self.db.transaction() as conn:
            for m in msgs:
                cur = conn.execute(
                    """
                    INSERT INTO messages
                      (contact_id, msg_id, msg_type, direction, sender, content,
                       raw_path, thumb_path, transcribed, intent, confidence, created_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(msg_id) DO NOTHING
                    RETURNING id
                    """,
                    (
                        m.contact_id,
                        m.msg_id,
                        m.msg_type,
                        m.direction,
                        m.sender,
                        m.content,
                        m.raw_path,
                        m.thumb_path,
                        int(m.transcribed),
                        m.intent,
                        m.confidence,
                        m.created_ts,
                    ),
                )
                row = cur.fetchone()
                if row is not None:
                    count += 1
                    if m.content:
                        conn.execute(
                            "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
                            (row["id"], m.content),
                        )
        return count

    def get_message(self, message_id: int) -> Optional[Message]:
        conn = self.db.connect()
        cur = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = cur.fetchone()
        return _row_to_message(row) if row else None

    def get_messages_by_types(self, types: list[str], limit: int = 5000) -> list[Message]:
        """按消息类型查询消息（用于媒体文件批量解析）。"""
        conn = self.db.connect()
        placeholders = ",".join("?" for _ in types)
        cur = conn.execute(
            f"SELECT * FROM messages WHERE msg_type IN ({placeholders})"
            f" AND raw_path = '' AND content != ''"
            f" ORDER BY created_ts DESC LIMIT {limit}",
            types,
        )
        return [_row_to_message(r) for r in cur.fetchall() if r]

    def update_message_raw_path(self, msg_id: str, raw_path: str) -> None:
        """更新消息的 raw_path（媒体文件路径）。"""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE messages SET raw_path = ? WHERE msg_id = ?",
                (raw_path, msg_id),
            )

    def list_messages(
        self,
        contact_id: Optional[int] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        msg_type: Optional[str] = None,
        limit: int = 500,
    ) -> List[Message]:
        """按条件列出消息（基础查询，不含全文搜索）。"""
        conn = self.db.connect()
        clauses: List[str] = []
        params: List[Any] = []
        if contact_id is not None:
            clauses.append("contact_id = ?")
            params.append(contact_id)
        if start_ts is not None:
            clauses.append("created_ts >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("created_ts <= ?")
            params.append(end_ts)
        if msg_type:
            clauses.append("msg_type = ?")
            params.append(msg_type)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT * FROM messages{where} ORDER BY created_ts ASC LIMIT ?"
        params.append(limit)
        cur = conn.execute(sql, params)
        return [_row_to_message(r) for r in cur.fetchall()]

    def search_messages(self, query: QueryFilter, limit: int = 200) -> List[Message]:
        """按 MCP 解析后的 QueryFilter 检索消息。

        过滤器分两类：
        - 硬过滤（始终生效）：客户、时间、消息类型
        - 软过滤（可降级）：关键词（FTS5/LIKE）、意图

        降级策略（避免跨语言/跨意图的零命中）：
        1. 客户 + 时间 + 类型 + 关键词 + 意图
        2. 若 0 条 → 去掉关键词，保留意图
        3. 若仍 0 条 → 去掉意图，仅保留硬过滤

        这样既能在数据匹配时做精准过滤，又能在用户中文提问、消息为西语
        或意图归类偏差时回退到"该客户该时段的全部消息"。
        """
        conn = self.db.connect()

        # ---- 硬过滤子句 ----
        base_clauses: List[str] = []
        base_params: List[Any] = []

        # 客户过滤（contact_ids）
        if query.contact_ids:
            placeholders = ",".join("?" * len(query.contact_ids))
            base_clauses.append(f"m.contact_id IN ({placeholders})")
            base_params.extend(query.contact_ids)

        # 客户名关键词 → 解析为 contact_ids 后并入
        if query.contact_keywords:
            sub_ids: List[int] = []
            for kw in query.contact_keywords:
                like = f"%{kw}%"
                cur = conn.execute(
                    "SELECT id FROM contacts WHERE nickname LIKE ? OR remark LIKE ? OR alias LIKE ?",
                    (like, like, like),
                )
                sub_ids.extend(r["id"] for r in cur.fetchall())
            if sub_ids:
                placeholders = ",".join("?" * len(sub_ids))
                base_clauses.append(f"m.contact_id IN ({placeholders})")
                base_params.extend(sub_ids)
            else:
                # 客户名关键词找不到任何客户 → 直接返回空
                return []

        # 时间过滤
        if query.start_ts is not None:
            base_clauses.append("m.created_ts >= ?")
            base_params.append(query.start_ts)
        if query.end_ts is not None:
            base_clauses.append("m.created_ts <= ?")
            base_params.append(query.end_ts)

        # 消息类型
        if query.msg_types:
            placeholders = ",".join("?" * len(query.msg_types))
            base_clauses.append(f"m.msg_type IN ({placeholders})")
            base_params.extend(query.msg_types)

        # ---- 软过滤：意图 ----
        intent_clauses: List[str] = []
        intent_params: List[Any] = []
        if query.intents:
            placeholders = ",".join("?" * len(query.intents))
            intent_clauses.append(f"m.intent IN ({placeholders})")
            intent_params.extend(query.intents)

        fts_available = self._is_fts_available(conn)

        def _exec(
            extra_clauses: List[str],
            extra_params: List[Any],
            keywords: List[str],
        ) -> List[Message]:
            """执行一次检索。extra_clauses 为软过滤子句（意图等），keywords 为 FTS/LIKE 关键词。"""
            all_clauses = base_clauses + extra_clauses
            all_params = base_params + extra_params
            where_sql = (" WHERE " + " AND ".join(all_clauses)) if all_clauses else ""

            if keywords:
                if fts_available:
                    # 多关键词用 OR；用双引号包裹避免被 FTS5 当作查询语法
                    fts_expr = " OR ".join(f'"{k}"' for k in keywords)
                    sql = f"""
                        SELECT m.* FROM messages m
                        JOIN messages_fts f ON f.rowid = m.id
                        WHERE messages_fts MATCH ?
                        {('AND ' + ' AND '.join(all_clauses)) if all_clauses else ''}
                        ORDER BY m.created_ts ASC LIMIT ?
                    """
                    cur = conn.execute(sql, (fts_expr, *all_params, limit))
                else:
                    # 回退 LIKE
                    kw_clauses = " OR ".join(["m.content LIKE ?" for _ in keywords])
                    kw_params = [f"%{k}%" for k in keywords]
                    if where_sql:
                        sql = f"SELECT m.* FROM messages m{where_sql} AND ({kw_clauses}) ORDER BY m.created_ts ASC LIMIT ?"
                        cur = conn.execute(sql, (*all_params, *kw_params, limit))
                    else:
                        sql = f"SELECT m.* FROM messages m WHERE ({kw_clauses}) ORDER BY m.created_ts ASC LIMIT ?"
                        cur = conn.execute(sql, (*kw_params, limit))
            else:
                sql = f"SELECT m.* FROM messages m{where_sql} ORDER BY m.created_ts ASC LIMIT ?"
                cur = conn.execute(sql, (*all_params, limit))
            return [_row_to_message(r) for r in cur.fetchall()]

        keywords = query.keywords or []
        # 是否存在硬过滤（客户/时间/类型）。仅在有硬过滤时才允许降级，
        # 否则纯关键词搜索（如"搜 xxx"）无命中应返回空，而不是回退成全表扫描。
        has_hard_filter = bool(base_clauses)

        # 1. 关键词 + 意图
        if keywords:
            results = _exec(intent_clauses, intent_params, keywords)
            if results:
                return results
            # 无硬过滤时不降级（避免纯关键词搜索回退成全表）
            if not has_hard_filter:
                return []
            # 2. 去掉关键词，保留意图
            results = _exec(intent_clauses, intent_params, [])
            if results:
                return results
            # 3. 去掉意图，仅硬过滤
            return _exec([], [], [])
        # 无关键词：意图 → 硬过滤 两级
        if intent_clauses:
            results = _exec(intent_clauses, intent_params, [])
            if results:
                return results
            if not has_hard_filter:
                return []
            return _exec([], [], [])
        return _exec([], [], [])

    def _is_fts_available(self, conn: sqlite3.Connection) -> bool:
        """检测 FTS5 是否可用。"""
        try:
            conn.execute("SELECT 1 FROM messages_fts LIMIT 0")
            return True
        except sqlite3.Error:
            return False

    def update_message_transcription(self, message_id: int, text: str) -> None:
        """语音转录完成后回写文本，并同步 FTS。"""
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE messages SET content = ?, transcribed = 1 WHERE id = ?",
                (text, message_id),
            )
            # 删除旧 FTS 行后重新插入
            conn.execute("DELETE FROM messages_fts WHERE rowid = ?", (message_id,))
            if text:
                conn.execute(
                    "INSERT INTO messages_fts(rowid, content) VALUES (?, ?)",
                    (message_id, text),
                )

    def update_message_intent(self, message_id: int, intent: str, confidence: float) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE messages SET intent = ?, confidence = ? WHERE id = ?",
                (intent, confidence, message_id),
            )

    def list_untranscribed_voice_messages(self, limit: int = 50) -> List[Message]:
        conn = self.db.connect()
        cur = conn.execute(
            "SELECT * FROM messages WHERE msg_type = 'voice' AND transcribed = 0 ORDER BY created_ts ASC LIMIT ?",
            (limit,),
        )
        return [_row_to_message(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------------
    # 待办
    # ------------------------------------------------------------------------
    def insert_todo(self, todo: Todo) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO todos
                  (contact_id, message_id, title, detail, due_ts, status, source, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    todo.contact_id,
                    todo.message_id,
                    todo.title,
                    todo.detail,
                    todo.due_ts,
                    todo.status,
                    todo.source,
                    todo.priority,
                ),
            )
            return cur.fetchone()["id"]

    def list_todos(
        self,
        status: Optional[str] = None,
        contact_id: Optional[int] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        order_by: str = "due_ts",
    ) -> List[Todo]:
        conn = self.db.connect()
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if contact_id is not None:
            clauses.append("contact_id = ?")
            params.append(contact_id)
        if start_ts is not None:
            clauses.append("created_ts >= ?")
            params.append(start_ts)
        if end_ts is not None:
            clauses.append("created_ts <= ?")
            params.append(end_ts)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        # 防注入：order_by 仅允许字段名
        allowed = {"due_ts", "created_ts", "priority", "status"}
        if order_by not in allowed:
            order_by = "due_ts"
        sql = f"SELECT * FROM todos{where} ORDER BY {order_by} ASC"
        cur = conn.execute(sql, params)
        return [_row_to_todo(r) for r in cur.fetchall()]

    def update_todo_status(self, todo_id: int, status: str) -> None:
        with self.db.transaction() as conn:
            completed_ts = _now() if status == "done" else None
            conn.execute(
                "UPDATE todos SET status = ?, completed_ts = ?, updated_ts = ? WHERE id = ?",
                (status, completed_ts, _now(), todo_id),
            )

    def update_todo(self, todo_id: int, fields: Dict[str, Any]) -> None:
        """通用更新。fields 限定为模型允许的字段。"""
        allowed = {"title", "detail", "due_ts", "status", "priority", "contact_id"}
        sets = []
        params: List[Any] = []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return
        sets.append("updated_ts = ?")
        params.append(_now())
        params.append(todo_id)
        with self.db.transaction() as conn:
            conn.execute(f"UPDATE todos SET {', '.join(sets)} WHERE id = ?", params)

    def delete_todo(self, todo_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    def todo_summary(self) -> Dict[str, int]:
        """按状态统计待办数量。"""
        conn = self.db.connect()
        cur = conn.execute(
            "SELECT status, COUNT(*) AS n FROM todos GROUP BY status"
        )
        return {row["status"]: row["n"] for row in cur.fetchall()}

    # ------------------------------------------------------------------------
    # 智能助手历史
    # ------------------------------------------------------------------------
    def insert_assistant_turn(self, turn: AssistantTurn) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO assistant_turns
                  (role, content, parsed_query, matched_msg_ids, latency_ms, engine)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    turn.role,
                    turn.content,
                    turn.parsed_query,
                    turn.matched_msg_ids,
                    turn.latency_ms,
                    turn.engine,
                ),
            )
            return cur.fetchone()["id"]

    def list_assistant_turns(self, limit: int = 50) -> List[AssistantTurn]:
        conn = self.db.connect()
        cur = conn.execute(
            "SELECT * FROM assistant_turns ORDER BY created_ts ASC, id ASC LIMIT ?",
            (limit,),
        )
        return [
            AssistantTurn(
                id=r["id"],
                role=r["role"],
                content=r["content"],
                parsed_query=r["parsed_query"],
                matched_msg_ids=r["matched_msg_ids"],
                latency_ms=r["latency_ms"],
                engine=r["engine"],
                created_ts=r["created_ts"],
            )
            for r in cur.fetchall()
        ]

    # ------------------------------------------------------------------------
    # 设置
    # ------------------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        conn = self.db.connect()
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_ts) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_ts = excluded.updated_ts
                """,
                (key, value, _now()),
            )

    def get_all_settings(self) -> Dict[str, str]:
        conn = self.db.connect()
        cur = conn.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}

    # ------------------------------------------------------------------------
    # 解密元数据
    # ------------------------------------------------------------------------
    def record_decrypt_run(
        self,
        wechat_version: str,
        db_path: str,
        key_source: str,
        msg_count: int,
        started_ts: int,
        finished_ts: Optional[int] = None,
    ) -> int:
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO decrypt_runs
                  (wechat_version, db_path, key_source, msg_count, started_ts, finished_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (wechat_version, db_path, key_source, msg_count, started_ts, finished_ts or _now()),
            )
            return cur.fetchone()["id"]

    def list_decrypt_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self.db.connect()
        cur = conn.execute(
            "SELECT * FROM decrypt_runs ORDER BY started_ts DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cur.fetchall()]


# ----------------------------------------------------------------------------
# 便捷函数：从 QueryFilter 提取 (start_ts, end_ts) 之外的展示文本
# ----------------------------------------------------------------------------
def query_filter_to_text(qf: QueryFilter) -> str:
    """把 QueryFilter 压缩成一行可读文本，便于日志/历史记录展示。"""
    parts: List[str] = []
    if qf.contact_keywords:
        parts.append("客户=" + "|".join(qf.contact_keywords))
    if qf.keywords:
        parts.append("关键词=" + "|".join(qf.keywords))
    if qf.relative_time:
        parts.append("时间=" + qf.relative_time)
    if qf.intents:
        parts.append("意图=" + "|".join(qf.intents))
    if qf.include_todos:
        parts.append("含待办")
        if qf.todo_status:
            parts.append(f"待办状态={qf.todo_status}")
    if qf.intent_action:
        parts.append(f"动作={qf.intent_action}")
    return " ".join(parts) or "全部消息"


def matched_ids_str(ids: Iterable[int]) -> str:
    return ",".join(str(i) for i in ids)


def parse_matched_ids(s: str) -> List[int]:
    if not s:
        return []
    return [int(x) for x in s.split(",") if x.strip().isdigit()]
