import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ContactOut, MessageOut } from '../types/api';
import IntentBadge from '../components/IntentBadge';
import Loading from '../components/Loading';

// 意图筛选选项
const INTENT_OPTIONS = [
  'all',
  'order',
  'quote',
  'info',
  'complaint',
  'greeting',
  'farewell',
  'confirm',
  'cancel',
  'other',
];

const INTENT_LABELS: Record<string, string> = {
  all: '全部意图',
  order: '下单',
  quote: '询价',
  info: '咨询',
  complaint: '投诉',
  greeting: '问候',
  farewell: '告别',
  confirm: '确认',
  cancel: '取消',
  other: '其他',
};

// 时间戳格式化
function fmtTs(ts: number | null): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes()
  )}`;
}

// 客户意图页：按意图筛选 + 点击客户展开消息及意图标签 + 一键重分类
export default function CustomerIntent() {
  const [contacts, setContacts] = useState<ContactOut[]>([]);
  const [intentFilter, setIntentFilter] = useState('all');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  // 加载客户列表
  const loadContacts = (intent?: string) => {
    setLoadingContacts(true);
    api
      .listContacts(intent === 'all' ? undefined : intent)
      .then((r) => setContacts(r.contacts || []))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoadingContacts(false));
  };

  useEffect(() => {
    loadContacts(intentFilter);
  }, [intentFilter]);

  // 选中客户后加载其所有消息
  useEffect(() => {
    if (selectedId == null) return;
    setLoadingMsgs(true);
    api
      .getContactMessages(selectedId, { limit: 1000 })
      .then((r) =>
        setMessages((r.messages || []).sort((a, b) => a.created_ts - b.created_ts))
      )
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoadingMsgs(false));
  }, [selectedId]);

  const selectedContact = useMemo(
    () => contacts.find((c) => c.id === selectedId) || null,
    [contacts, selectedId]
  );

  // 一键重分类当前客户的消息意图
  const handleReclassify = () => {
    if (selectedId == null) return;
    setBusy(true);
    setErr('');
    api
      .reclassifyContact(selectedId, 1000)
      .then(() => {
        // 重分类完成后重新拉取消息以展示新意图
        return api.getContactMessages(selectedId, { limit: 1000 });
      })
      .then((r) => setMessages((r.messages || []).sort((a, b) => a.created_ts - b.created_ts)))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="intent-layout">
      {/* 左侧：客户列表 */}
      <div className="intent-list-pane">
        <div className="intent-list-head">
          <select
            className="select"
            value={intentFilter}
            onChange={(e) => setIntentFilter(e.target.value)}
          >
            {INTENT_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {INTENT_LABELS[k]}
              </option>
            ))}
          </select>
        </div>
        <div className="contact-list">
          {loadingContacts ? (
            <Loading />
          ) : contacts.length === 0 ? (
            <div className="empty-state">暂无客户</div>
          ) : (
            contacts.map((c) => (
              <div
                key={c.id}
                className={`contact-item ${selectedId === c.id ? 'active' : ''}`}
                onClick={() => setSelectedId(c.id)}
              >
                <div className="contact-item-name">
                  <span className="ellipsis">{c.nickname || c.remark || c.wxid}</span>
                  <IntentBadge intent={c.last_intent} />
                </div>
                <div className="contact-item-meta">
                  {c.region ? `${c.region} · ` : ''}
                  {c.last_msg_ts ? fmtTs(c.last_msg_ts) : '无消息'}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 右侧：客户消息及意图标签详情 */}
      <div className="intent-detail-pane">
        {selectedId == null ? (
          <div className="empty-state" style={{ marginTop: 80 }}>
            请在左侧选择客户查看意图详情
          </div>
        ) : (
          <>
            <div className="intent-detail-head">
              <div>
                <span className="text-bold">{selectedContact?.nickname || selectedContact?.wxid}</span>
                {selectedContact?.last_intent ? (
                  <span style={{ marginLeft: 8 }}>
                    <IntentBadge
                      intent={selectedContact.last_intent}
                    />
                  </span>
                ) : null}
              </div>
              <button className="btn btn-blue btn-sm" disabled={busy} onClick={handleReclassify}>
                {busy ? '识别中...' : '重新识别意图'}
              </button>
            </div>
            <div className="intent-detail-body">
              {err ? (
                <div className="empty-state">加载失败：{err}</div>
              ) : loadingMsgs ? (
                <Loading />
              ) : messages.length === 0 ? (
                <div className="empty-state">暂无消息</div>
              ) : (
                messages.map((m) => (
                  <div className="intent-msg-row" key={m.id}>
                    <div className="intent-msg-meta">
                      <span>{m.direction === 'send' ? '我' : m.sender || '对方'}</span>
                      <span>{fmtTs(m.created_ts)}</span>
                      <IntentBadge intent={m.intent} confidence={m.confidence} />
                    </div>
                    <div className="intent-msg-content">
                      {m.msg_type === 'voice'
                        ? m.transcribed
                          ? m.content || '(无转录)'
                          : '🎙️ 语音消息（未转录）'
                        : m.msg_type === 'image'
                        ? '[图片]'
                        : m.content || '(空消息)'}
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
