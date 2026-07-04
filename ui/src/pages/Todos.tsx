import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ContactOut, TodoCreateRequest, TodoOut, TodoSummaryResponse } from '../types/api';
import TodoCard from '../components/TodoCard';
import Loading from '../components/Loading';

// 状态中文文案
const STATUS_LABELS: Record<string, string> = {
  all: '全部状态',
  pending: '待处理',
  doing: '进行中',
  done: '已完成',
  cancelled: '已取消',
};

// 排序选项
const ORDER_OPTIONS = [
  { key: 'due_ts', label: '按截止时间' },
  { key: 'created_ts', label: '按创建时间' },
  { key: 'status', label: '按状态' },
];

// 时间戳转 datetime-local 输入值
function tsToInput(ts: number | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(
    d.getMinutes()
  )}`;
}

// datetime-local 输入值转时间戳
function inputToTs(v: string): number | undefined {
  if (!v) return undefined;
  const t = Math.floor(new Date(v).getTime() / 1000);
  return isNaN(t) ? undefined : t;
}

// 待办页：汇总卡片 + 筛选 + 列表 + 新增/编辑/删除
export default function Todos() {
  const [todos, setTodos] = useState<TodoOut[]>([]);
  const [summary, setSummary] = useState<TodoSummaryResponse | null>(null);
  const [contacts, setContacts] = useState<ContactOut[]>([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [contactFilter, setContactFilter] = useState('');
  const [orderBy, setOrderBy] = useState('due_ts');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [showModal, setShowModal] = useState(false);

  // 新建待办表单状态
  const [form, setForm] = useState<TodoCreateRequest>({
    title: '',
    detail: '',
    priority: 'medium',
    contact_id: undefined,
    due_ts: undefined,
  });

  // 加载待办列表
  const loadTodos = () => {
    setLoading(true);
    const params: { status?: string; contact_id?: number; order_by?: string } = {
      order_by: orderBy,
    };
    if (statusFilter !== 'all') params.status = statusFilter;
    if (contactFilter) params.contact_id = Number(contactFilter);
    api
      .listTodos(params)
      .then((r) => setTodos(r.todos || []))
      .catch((e) => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  };

  // 加载汇总与客户列表
  const loadSummary = () => {
    api.getTodoSummary().then(setSummary).catch(() => {});
  };
  const loadContacts = () => {
    api.listContacts().then((r) => setContacts(r.contacts || [])).catch(() => {});
  };

  useEffect(() => {
    loadTodos();
  }, [statusFilter, contactFilter, orderBy]);

  useEffect(() => {
    loadSummary();
    loadContacts();
  }, []);

  // 状态切换
  const handleStatusChange = (id: number, status: string) => {
    api
      .updateTodo(id, { status })
      .then(() => loadTodos())
      .then(() => loadSummary())
      .catch((e) => setErr(String(e.message || e)));
  };

  // 删除
  const handleDelete = (id: number) => {
    if (!confirm('确认删除该待办？')) return;
    api
      .deleteTodo(id)
      .then(() => loadTodos())
      .then(() => loadSummary())
      .catch((e) => setErr(String(e.message || e)));
  };

  // 新建提交
  const handleCreate = () => {
    if (!form.title.trim()) {
      setErr('标题不能为空');
      return;
    }
    api
      .createTodo(form)
      .then(() => {
        setShowModal(false);
        setForm({ title: '', detail: '', priority: 'medium', contact_id: undefined, due_ts: undefined });
        loadTodos();
        loadSummary();
      })
      .catch((e) => setErr(String(e.message || e)));
  };

  const byStatus = summary?.by_status || {};

  return (
    <div>
      {err ? <div className="empty-state">提示：{err}</div> : null}

      {/* 汇总统计卡片 */}
      <div className="todo-grid">
        {(['pending', 'doing', 'done', 'cancelled'] as const).map((s) => (
          <div className="card" key={s}>
            <div className="muted text-sm">{STATUS_LABELS[s]}</div>
            <div className="stat-card-value">{byStatus[s] || 0}</div>
          </div>
        ))}
      </div>

      {/* 筛选条 */}
      <div className="filter-bar">
        <select
          className="select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className="select"
          value={contactFilter}
          onChange={(e) => setContactFilter(e.target.value)}
        >
          <option value="">全部客户</option>
          {contacts.map((c) => (
            <option key={c.id} value={c.id}>
              {c.nickname || c.remark || c.wxid}
            </option>
          ))}
        </select>
        <select
          className="select"
          value={orderBy}
          onChange={(e) => setOrderBy(e.target.value)}
        >
          {ORDER_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        <button className="btn btn-primary" onClick={() => setShowModal(true)}>
          + 新建待办
        </button>
      </div>

      {/* 待办列表 */}
      {loading ? (
        <Loading />
      ) : todos.length === 0 ? (
        <div className="empty-state">暂无待办</div>
      ) : (
        <div className="todo-list">
          {todos.map((t) => (
            <TodoCard
              key={t.id}
              todo={t}
              onStatusChange={handleStatusChange}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {/* 新建待办模态框 */}
      {showModal ? (
        <div className="modal-mask" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">新建待办</div>
            <div className="modal-field">
              <div className="modal-field-label">标题</div>
              <input
                className="input"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </div>
            <div className="modal-field">
              <div className="modal-field-label">关联客户</div>
              <select
                className="select"
                value={form.contact_id ?? ''}
                onChange={(e) =>
                  setForm({
                    ...form,
                    contact_id: e.target.value ? Number(e.target.value) : undefined,
                  })
                }
              >
                <option value="">不关联</option>
                {contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nickname || c.remark || c.wxid}
                  </option>
                ))}
              </select>
            </div>
            <div className="modal-field">
              <div className="modal-field-label">详情</div>
              <textarea
                className="textarea"
                value={form.detail}
                onChange={(e) => setForm({ ...form, detail: e.target.value })}
              />
            </div>
            <div className="modal-field">
              <div className="modal-field-label">截止时间</div>
              <input
                type="datetime-local"
                className="input"
                value={tsToInput(form.due_ts ?? null)}
                onChange={(e) => setForm({ ...form, due_ts: inputToTs(e.target.value) })}
              />
            </div>
            <div className="modal-field">
              <div className="modal-field-label">优先级</div>
              <select
                className="select"
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                <option value="high">高</option>
                <option value="medium">中</option>
                <option value="low">低</option>
              </select>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowModal(false)}>
                取消
              </button>
              <button className="btn btn-primary" onClick={handleCreate}>
                创建
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
