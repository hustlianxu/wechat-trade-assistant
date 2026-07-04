import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { DashboardData, ContactOut, TodoOut } from '../types/api';
import IntentBadge from '../components/IntentBadge';
import Loading from '../components/Loading';

// 时间戳格式化
function fmtTs(ts: number | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes()
  )}`;
}

// 仪表盘：三张统计卡片 + 最近客户 + 最近待办
export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [err, setErr] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    api
      .getDashboard()
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e) => {
        if (alive) setErr(String(e.message || e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <Loading />;
  if (err) return <div className="empty-state">加载失败：{err}</div>;
  if (!data) return <div className="empty-state">暂无数据</div>;

  const recentContacts = (data.recent_contacts || []) as ContactOut[];
  const recentTodos = (data.recent_todos || []) as TodoOut[];

  return (
    <div>
      {/* 顶部三张统计卡片 */}
      <div className="stat-cards">
        <div className="stat-card">
          <div className="stat-card-icon green">📋</div>
          <div className="stat-card-label">今日待办</div>
          <div className="stat-card-value">{data.today_todo_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-icon orange">⏳</div>
          <div className="stat-card-label">待处理待办</div>
          <div className="stat-card-value">{data.pending_todo_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-icon blue">🎯</div>
          <div className="stat-card-label">未读意图客户</div>
          <div className="stat-card-value">{data.unread_intent_contacts}</div>
        </div>
      </div>

      {/* 下方两栏 */}
      <div className="dash-cols">
        <div className="card">
          <div className="panel-title">最近客户</div>
          {recentContacts.length === 0 ? (
            <div className="empty-state">暂无客户</div>
          ) : (
            recentContacts.slice(0, 10).map((c) => (
              <div className="list-row" key={c.id}>
                <span className="ellipsis">{c.nickname || c.remark || c.wxid}</span>
                <IntentBadge intent={c.last_intent} />
              </div>
            ))
          )}
        </div>
        <div className="card">
          <div className="panel-title">最近待办</div>
          {recentTodos.length === 0 ? (
            <div className="empty-state">暂无待办</div>
          ) : (
            recentTodos.slice(0, 10).map((t) => (
              <div className="list-row" key={t.id}>
                <span className="ellipsis">{t.title}</span>
                <span className="muted text-sm">{t.due_ts ? fmtTs(t.due_ts) : '无截止'}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
