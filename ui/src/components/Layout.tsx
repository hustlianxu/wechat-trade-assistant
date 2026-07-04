import type { ReactNode } from 'react';
import type { PageKey } from '../App';

// 各页面顶栏标题
const PAGE_TITLES: Record<PageKey, string> = {
  dashboard: '仪表盘',
  chat: '聊天记录',
  intent: '客户意图',
  todos: '待办',
  assistant: '智能助手',
  settings: '设置',
};

interface LayoutProps {
  page: PageKey;
  children: ReactNode;
}

// 顶栏 + 内容容器
export default function Layout({ page, children }: LayoutProps) {
  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-title">{PAGE_TITLES[page]}</div>
      </header>
      <main className="layout-content">{children}</main>
    </div>
  );
}
