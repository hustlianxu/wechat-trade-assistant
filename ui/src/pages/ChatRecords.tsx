import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ContactOut, MessageOut } from '../types/api';
import MessageBubble from '../components/MessageBubble';
import Loading from '../components/Loading';

// 时间范围选项
const RANGES = [
  { key: 'all', label: '全部', days: 0 },
  { key: 'today', label: '今天', days: 1 },
  { key: '7d', label: '近7天', days: 7 },
  { key: '30d', label: '近30天', days: 30 },
];

// 时间戳格式化
function fmtTs(ts: number | null): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 聊天记录页：左侧客户列表 + 右侧消息流
export default function ChatRecords() {
  const [contacts, setContacts] = useState<ContactOut[]>([]);
  const [contactFilter, setContactFilter] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rawMessages, setRawMessages] = useState<MessageOut[]>([]);
  const [range, setRange] = useState('all');
  const [keyword, setKeyword] = useState('');
  const [loadingContacts, setLoadingContacts] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [err, setErr] = useState('');

  // 加载客户列表
  useEffect(() => {
    let alive = true;
    setLoadingContacts(true);
    api
      .listContacts()
      .then((r) => {
        if (alive) setContacts(r.contacts || []);
      })
      .catch((e) => {
        if (alive) setErr(String(e.message || e));
      })
      .finally(() => {
        if (alive) setLoadingContacts(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 选中客户或切换时间范围时重新加载消息
  useEffect(() => {
    if (selectedId == null) return;
    setLoadingMsgs(true);
    setErr('');
    const now = Math.floor(Date.now() / 1000);
    const rangeConf = RANGES.find((r) => r.key === range);
    const params: { limit: number; start_ts?: number } = { limit: 1000 };
    if (rangeConf && rangeConf.days > 0) params.start_ts = now - rangeConf.days * 86400;
    api
      .getContactMessages(selectedId, params)
      .then((r) => setRawMessages(r.messages || []))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoadingMsgs(false));
  }, [selectedId, range]);

  // 客户列表本地搜索过滤
  const filteredContacts = useMemo(() => {
    const kw = contactFilter.trim().toLowerCase();
    if (!kw) return contacts;
    return contacts.filter(
      (c) =>
        (c.nickname || '').toLowerCase().includes(kw) ||
        (c.remark || '').toLowerCase().includes(kw) ||
        (c.wxid || '').toLowerCase().includes(kw)
    );
  }, [contacts, contactFilter]);

  // 关键词本地过滤 + 按时间升序
  const displayMessages = useMemo(() => {
    let msgs = [...rawMessages];
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      msgs = msgs.filter((m) => (m.content || '').toLowerCase().includes(kw));
    }
    msgs.sort((a, b) => a.created_ts - b.created_ts);
    return msgs;
  }, [rawMessages, keyword]);

  return (
    <div className="chat-layout">
      {/* 左栏：客户列表 */}
      <div className="chat-sidebar">
        <div className="chat-sidebar-head">
          <input
            className="input"
            placeholder="搜索客户"
            value={contactFilter}
            onChange={(e) => setContactFilter(e.target.value)}
          />
        </div>
        <div className="contact-list">
          {loadingContacts ? (
            <Loading />
          ) : filteredContacts.length === 0 ? (
            <div className="empty-state">暂无客户</div>
          ) : (
            filteredContacts.map((c) => (
              <div
                key={c.id}
                className={`contact-item ${selectedId === c.id ? 'active' : ''}`}
                onClick={() => setSelectedId(c.id)}
              >
                <div className="contact-item-name">
                  <span className="ellipsis">{c.nickname || c.remark || c.wxid}</span>
                  {c.last_msg_ts ? (
                    <span className="contact-item-meta">{fmtTs(c.last_msg_ts)}</span>
                  ) : null}
                </div>
                {c.region ? <div className="contact-item-meta">{c.region}</div> : null}
              </div>
            ))
          )}
        </div>
      </div>

      {/* 右栏：消息流 */}
      <div className="chat-main">
        {selectedId == null ? (
          <div className="empty-state" style={{ marginTop: 80 }}>
            请在左侧选择客户查看聊天记录
          </div>
        ) : (
          <>
            <div className="chat-toolbar">
              <span className="muted text-sm">时间范围：</span>
              <select
                className="select"
                style={{ width: 'auto' }}
                value={range}
                onChange={(e) => setRange(e.target.value)}
              >
                {RANGES.map((r) => (
                  <option key={r.key} value={r.key}>
                    {r.label}
                  </option>
                ))}
              </select>
              <input
                className="input"
                style={{ flex: 1, minWidth: 120 }}
                placeholder="关键词筛选消息内容"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
            <div className="chat-stream">
              {err ? (
                <div className="empty-state">加载失败：{err}</div>
              ) : loadingMsgs ? (
                <Loading />
              ) : displayMessages.length === 0 ? (
                <div className="empty-state">暂无消息</div>
              ) : (
                displayMessages.map((m) => <MessageBubble key={m.id} message={m} />)
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
