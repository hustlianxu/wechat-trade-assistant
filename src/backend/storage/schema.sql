-- ============================================================================
-- 南美外贸微信智能助手 - 本地 SQLite 数据库 Schema
-- 所有表均在用户本地数据库文件中，绝不外传
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 客户/联系人表
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wxid            TEXT NOT NULL UNIQUE,         -- 微信内部 ID
    nickname        TEXT NOT NULL DEFAULT '',     -- 微信昵称
    remark          TEXT NOT NULL DEFAULT '',     -- 用户备注名（外贸客户常用真名）
    alias           TEXT NOT NULL DEFAULT '',     -- 微信号
    region          TEXT NOT NULL DEFAULT '',     -- 地区
    last_intent     TEXT NOT NULL DEFAULT '',     -- 最近一次识别到的意图
    last_intent_ts  INTEGER,                      -- 最近意图时间戳（Unix 秒）
    last_msg_ts     INTEGER,                      -- 最近消息时间戳
    note            TEXT NOT NULL DEFAULT '',     -- 用户自定义备注
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    updated_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_contacts_remark ON contacts(remark);
CREATE INDEX IF NOT EXISTS idx_contacts_last_intent ON contacts(last_intent);

-- ----------------------------------------------------------------------------
-- 消息表：文字 / 图片 / 语音 / 系统 / 其他
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER NOT NULL,
    msg_id          TEXT,                         -- 微信原始消息 ID（去重用）
    msg_type        TEXT NOT NULL,                -- text/image/voice/system/file/other
    direction       TEXT NOT NULL DEFAULT 'in',   -- in=对方发来 out=我发出
    sender          TEXT NOT NULL DEFAULT '',     -- 群聊里区分发送者
    content         TEXT NOT NULL DEFAULT '',     -- 文本内容（语音转录后也写这里）
    raw_path        TEXT NOT NULL DEFAULT '',     -- 原始文件路径（图片/语音 .dat 文件）
    thumb_path      TEXT NOT NULL DEFAULT '',     -- 解密后缩略图/转码后 wav 路径
    transcribed     INTEGER NOT NULL DEFAULT 0,   -- 语音是否已转录
    intent          TEXT NOT NULL DEFAULT '',     -- 该条消息的意图标签
    confidence      REAL NOT NULL DEFAULT 0.0,    -- 意图置信度
    created_ts      INTEGER NOT NULL,             -- 消息时间戳（Unix 秒）
    ingested_ts     INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
    UNIQUE(msg_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_contact_ts ON messages(contact_id, created_ts);
CREATE INDEX IF NOT EXISTS idx_messages_type ON messages(msg_type);
CREATE INDEX IF NOT EXISTS idx_messages_intent ON messages(intent);
CREATE INDEX IF NOT EXISTS idx_messages_created_ts ON messages(created_ts);

-- 全文搜索虚拟表（中文/西班牙语混合，使用 unicode61 分词，简单 trigram 兜底）
-- 注意：FTS5 在大多数 SQLite 中可用；如不可用，repository 会回退到 LIKE 查询。
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- ----------------------------------------------------------------------------
-- 待办事项表
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS todos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id      INTEGER,                      -- 关联客户（可空，表示通用待办）
    message_id      INTEGER,                      -- 关联消息来源（自动提取时填）
    title           TEXT NOT NULL,                -- 待办标题
    detail          TEXT NOT NULL DEFAULT '',     -- 详情
    due_ts          INTEGER,                      -- 截止时间戳
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/doing/done/cancelled
    source          TEXT NOT NULL DEFAULT 'manual',   -- manual/auto_extract
    priority        TEXT NOT NULL DEFAULT 'normal',   -- low/normal/high/urgent
    created_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    updated_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    completed_ts    INTEGER,
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_due ON todos(due_ts);
CREATE INDEX IF NOT EXISTS idx_todos_contact ON todos(contact_id);

-- ----------------------------------------------------------------------------
-- 智能助手对话历史
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS assistant_turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role            TEXT NOT NULL,                -- user / assistant
    content         TEXT NOT NULL,
    parsed_query    TEXT NOT NULL DEFAULT '',     -- 解析出的结构化查询（JSON）
    matched_msg_ids TEXT NOT NULL DEFAULT '',     -- 命中消息 ID（逗号分隔）
    latency_ms      INTEGER NOT NULL DEFAULT 0,   -- 本次响应耗时
    engine          TEXT NOT NULL DEFAULT 'local',-- local / cloud
    created_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_assistant_ts ON assistant_turns(created_ts);

-- ----------------------------------------------------------------------------
-- 应用设置（键值对存储）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL DEFAULT '',
    updated_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- ----------------------------------------------------------------------------
-- 解密元数据：记录已导入的微信数据库快照
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decrypt_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    wechat_version  TEXT NOT NULL,                -- 微信版本号
    db_path         TEXT NOT NULL,                -- 来源数据库路径
    key_source      TEXT NOT NULL,                -- memory / registry / manual
    msg_count       INTEGER NOT NULL DEFAULT 0,
    started_ts      INTEGER NOT NULL,
    finished_ts     INTEGER
);
