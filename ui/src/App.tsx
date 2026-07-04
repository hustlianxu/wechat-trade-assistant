import { useState } from 'react';
import Sidebar from './components/Sidebar';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import ChatRecords from './pages/ChatRecords';
import CustomerIntent from './pages/CustomerIntent';
import Todos from './pages/Todos';
import Assistant from './pages/Assistant';
import Settings from './pages/Settings';

// 可切换的页面键
export type PageKey = 'dashboard' | 'chat' | 'intent' | 'todos' | 'assistant' | 'settings';

// 顶层应用：通过内部状态切换页面，避免引入路由库
export default function App() {
  const [currentPage, setCurrentPage] = useState<PageKey>('dashboard');

  return (
    <div className="app-shell">
      <Sidebar current={currentPage} onChange={setCurrentPage} />
      <Layout page={currentPage}>{renderPage(currentPage)}</Layout>
    </div>
  );
}

// 根据当前页面键渲染对应页面组件
function renderPage(page: PageKey) {
  switch (page) {
    case 'dashboard':
      return <Dashboard />;
    case 'chat':
      return <ChatRecords />;
    case 'intent':
      return <CustomerIntent />;
    case 'todos':
      return <Todos />;
    case 'assistant':
      return <Assistant />;
    case 'settings':
      return <Settings />;
    default:
      return null;
  }
}
