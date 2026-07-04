"""本地 SQLite 数据库连接管理。

设计要点：
1. 单文件 SQLite，所有数据落盘在用户本地，绝不联网
2. 自动按 schema.sql 初始化/升级
3. 支持可选的 SQLCipher 加密（如用户在设置里开启数据库密码）
4. 连接线程局部，避免跨线程使用
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

# 本文件所在目录
SCHEMA_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA = SCHEMA_DIR / "schema.sql"

# 默认数据目录：项目根/data/local.db
# 打包后会改到用户目录，由 config.py 决定
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "local.db"


class Database:
    """SQLite 数据库封装，线程安全。

    用法：
        db = Database("/path/to/local.db")
        db.init_schema()
        with db.connect() as conn:
            conn.execute("SELECT 1")
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        password: Optional[str] = None,
        schema_path: Optional[Path] = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.password = password
        self.schema_path = Path(schema_path) if schema_path else DEFAULT_SCHEMA
        self._local = threading.local()

        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _make_conn(self) -> sqlite3.Connection:
        """创建一个新的 SQLite 连接。

        如果密码非空且环境里有 pysqlcipher3，则启用加密；
        否则回退到标准 sqlite3（开发/沙箱环境）。
        """
        if self.password:
            try:
                # 延迟导入：沙箱里通常没有 pysqlcipher3
                from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore

                conn = sqlcipher.connect(str(self.db_path))
                conn.execute(f"PRAGMA key = '{self.password}';")
                # SQLCipher 4 默认参数；微信 4.0 也是 SQLCipher 4
                conn.execute("PRAGMA cipher_compatibility = 4;")
            except ImportError:
                # 没装 pysqlcipher3，警告并回退（不阻断流程）
                print(
                    "[storage] 警告：未安装 pysqlcipher3，回退到未加密 SQLite。"
                    "如需加密本地库，请先 pip install pysqlcipher3"
                )
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        else:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)

        # 启用外键
        conn.execute("PRAGMA foreign_keys = ON;")
        # 提升批量写入性能
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def connect(self) -> sqlite3.Connection:
        """获取当前线程的连接（懒加载，复用）。

        返回的连接未自动关闭，调用方应在退出时调用 close_all()。
        对于短任务请使用 with db.transaction()。
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._make_conn()
            self._local.conn = conn
        return conn

    def init_schema(self) -> None:
        """按 schema.sql 初始化数据库（幂等）。"""
        sql = self.schema_path.read_text(encoding="utf-8")
        conn = self.connect()
        conn.executescript(sql)
        conn.commit()

    def transaction(self):
        """上下文管理器：进入事务，正常退出提交，异常回滚。

        with db.transaction() as conn:
            conn.execute("INSERT ...")
        """
        return _Transaction(self)

    def close_all(self) -> None:
        """关闭当前线程的连接。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


class _Transaction:
    """简单的 transaction 上下文管理器。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = self.db.connect()
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.conn is not None
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            # 不关闭连接，仅结束事务（连接由 db 复用）
            self.conn = None


# 模块级默认实例：供简单场景直接 import 使用
_default_db: Optional[Database] = None
_default_lock = threading.Lock()


def get_default_db() -> Database:
    """获取全局默认 Database 实例（懒加载）。"""
    global _default_db
    if _default_db is None:
        with _default_lock:
            if _default_db is None:
                _default_db = Database()
                _default_db.init_schema()
    return _default_db


def reset_default_db() -> None:
    """重置默认实例（测试用）。"""
    global _default_db
    if _default_db is not None:
        _default_db.close_all()
    _default_db = None
