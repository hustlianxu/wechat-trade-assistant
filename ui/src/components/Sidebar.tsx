import type { PageKey } from '../App';

// 侧边栏导航项定义
interface NavItem {
  key: PageKey;
  label: string;
  icon: string;
}

// 6 个主导航项
const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', label: '仪表盘', icon: '📊' },
  { key: 'chat', label: '聊天记录', icon: '💬' },
  { key: 'intent', label: '客户意图', icon: '🎯' },
  { key: 'todos', label: '待办', icon: '✅' },
  { key: 'assistant', label: '智能助手', icon: '🤖' },
  { key: 'settings', label: '设置', icon: '⚙️' },
];

interface SidebarProps {
  current: PageKey;
  onChange: (page: PageKey) => void;
}

// 左侧导航栏：应用 logo + 导航项列表
export default function Sidebar({ current, onChange }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">W</div>
        <div className="sidebar-logo-text">
          <div className="sidebar-logo-title">外贸助手</div>
          <div className="sidebar-logo-sub">WeChat Trade</div>
        </div>
      </div>
      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            className={`sidebar-item ${current === item.key ? 'active' : ''}`}
            onClick={() => onChange(item.key)}
          >
            <span className="sidebar-item-icon">{item.icon}</span>
            <span className="sidebar-item-label">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">v1.0.0</div>
    </aside>
  );
}
