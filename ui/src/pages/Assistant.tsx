import { useEffect, useRef, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import type { AssistantMessageOut } from '../types/api';
import IntentBadge from '../components/IntentBadge';
import Loading from '../components/Loading';

// 时间戳格式化
function fmtTs(ts: number | null): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 单条助手回合：用户气泡 + 助手卡片
function TurnView({ turn }: { turn: AssistantMessageOut }) {
  // 轮次中的用户提问文本
  const userText = turn.parsed_query || '';
  // 引擎徽章
  const engineLabel = turn.engine === 'cloud' ? '云端' : '本地';
  const engineCls = turn.engine === 'cloud' ? 'engine-cloud' : 'engine-local';

  return (
    <>
      {/* 用户消息靠右（绿色） */}
      {userText ? (
        <div className="assistant-turn user">
          <div className="assistant-turn-user-bubble">{userText}</div>
        </div>
      ) : null}

      {/* 助手消息靠左（白色卡片） */}
      <div className="assistant-turn">
        <div className="assistant-turn-assistant-bubble">
          <div className="assistant-meta">
            <span className={`engine-badge ${engineCls}`}>{engineLabel}</span>
            <span>耗时 {turn.latency_ms}ms</span>
            {turn.created_ts ? <span>· {fmtTs(turn.created_ts)}</span> : null}
          </div>
          <div className="assistant-content">{turn.content || '(无回复内容)'}</div>

          <CollapsibleSection
            title={`匹配到的聊天记录 ${turn.messages.length} 条`}
            items={turn.messages.slice(0, 5).map((m) => ({
              id: String(m.id),
              content: `${m.direction === 'send' ? '我' : m.sender || '对方'}：${
                m.msg_type === 'voice'
                  ? m.transcribed
                    ? m.content || '(无转录)'
                    : '语音未转录'
                  : m.msg_type === 'image'
                  ? '[图片]'
                  : m.content
              } （${fmtTs(m.created_ts)}）`,
              extra: m.intent ? <IntentBadge intent={m.intent} confidence={m.confidence} /> : null,
            }))}
          />

          <CollapsibleSection
            title={`相关待办 ${turn.todos.length} 条`}
            items={turn.todos.slice(0, 5).map((t) => ({
              id: String(t.id),
              content: `${t.title}${t.due_ts ? `（截止 ${fmtTs(t.due_ts)}）` : ''}`,
              extra: <span className="badge">{t.status}</span>,
            }))}
          />

          {turn.contacts.length > 0 ? (
            <div className="assistant-section">
              <div className="assistant-section-title">涉及客户</div>
              <div className="assistant-contacts">
                {turn.contacts.map((c) => (
                  <span className="badge" key={c.id}>
                    {c.nickname || c.remark || c.wxid}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </>
  );
}

// 可折叠区块
function CollapsibleSection({
  title,
  items,
}: {
  title: string;
  items: Array<{ id: string; content: string; extra?: ReactNode }>;
}) {
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="assistant-section">
      <div className="assistant-section-title" onClick={() => setOpen((v) => !v)}>
        <span>{open ? '▾' : '▸'}</span>
        <span>{title}</span>
      </div>
      {open ? (
        <div className="assistant-section-body">
          {items.map((it) => (
            <div className="assistant-match-row" key={it.id}>
              <span>{it.content}</span>
              {it.extra ? <span style={{ marginLeft: 6 }}>{it.extra}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// 智能助手页：全屏聊天界面
export default function Assistant() {
  const [turns, setTurns] = useState<AssistantMessageOut[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const streamRef = useRef<HTMLDivElement>(null);

  // 加载历史
  useEffect(() => {
    api
      .getAssistantHistory(50)
      .then((r) => setTurns(r.turns || []))
      .catch((e) => setErr(String(e.message || e)));
  }, []);

  // 新消息时滚动到底部
  useEffect(() => {
    if (streamRef.current) {
      streamRef.current.scrollTop = streamRef.current.scrollHeight;
    }
  }, [turns, loading]);

  // 发送提问
  const handleSend = () => {
    const text = input.trim();
    if (!text || loading) return;
    setLoading(true);
    setErr('');
    api
      .queryAssistant({ text, use_cloud: false })
      .then((res) => {
        setTurns((prev) => [...prev, res]);
        setInput('');
      })
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  };

  // 仅前端清空历史
  const handleClear = () => {
    setTurns([]);
  };

  return (
    <div className="assistant-wrap">
      <div className="assistant-head">
        <div className="text-bold">智能助手</div>
        <button className="btn btn-sm" onClick={handleClear}>
          清空历史
        </button>
      </div>
      <div className="assistant-stream" ref={streamRef}>
        {err ? <div className="empty-state">提示：{err}</div> : null}
        {turns.length === 0 && !loading ? (
          <div className="empty-state">向助手提问，获取客户/消息/待办的综合答复</div>
        ) : null}
        {turns.map((t, i) => (
          <TurnView key={i} turn={t} />
        ))}
        {loading ? <Loading text="助手思考中..." /> : null}
      </div>
      <div className="assistant-input">
        <textarea
          placeholder="输入问题，回车发送，Shift+回车换行"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <button className="btn btn-primary" disabled={loading || !input.trim()} onClick={handleSend}>
          发送
        </button>
      </div>
    </div>
  );
}
