import type { TodoOut } from '../types/api';

interface TodoCardProps {
  todo: TodoOut;
  onStatusChange: (id: number, status: string) => void;
  onDelete: (id: number) => void;
}

// 待办状态到中文文案的映射
const STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  doing: '进行中',
  done: '已完成',
  cancelled: '已取消',
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

// 待办卡片：含状态切换下拉与删除按钮
export default function TodoCard({ todo, onStatusChange, onDelete }: TodoCardProps) {
  const priority = todo.priority || 'medium';
  const priorityCls = `priority-${priority}`;
  const statusCls = `status-${todo.status}`;

  return (
    <div className={`todo-card ${priorityCls} ${statusCls}`}>
      <div className="todo-card-head">
        <div className="todo-card-title">{todo.title}</div>
        <button className="btn btn-danger btn-sm" onClick={() => onDelete(todo.id)}>
          删除
        </button>
      </div>
      {todo.detail ? <div className="todo-card-detail">{todo.detail}</div> : null}
      <div className="todo-card-foot">
        <div className="flex gap-8">
          <span>来源：{todo.source || '-'}</span>
          {todo.due_ts ? <span>截止：{fmtTs(todo.due_ts)}</span> : null}
        </div>
        <select
          className="todo-status-select"
          value={todo.status}
          onChange={(e) => onStatusChange(todo.id, e.target.value)}
        >
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
