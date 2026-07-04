import { app, BrowserWindow, shell, dialog } from 'electron';
import * as path from 'path';
import { startPythonBackend, stopPythonBackend } from './python_runner';
import {
  isPortInUse,
  getProcessUsingPort,
  killProcess,
  findFreePort,
  waitForPortFree,
} from './port_manager';

// 主窗口引用，避免被垃圾回收
let mainWindow: BrowserWindow | null = null;

// 后端服务端口，由 python_runner 解析 READY 行得到，默认 8765
let backendPort: number = 8765;

// 后端启动错误信息（供前端查询）
let backendError: string | null = null;

// 默认端口
const DEFAULT_PORT = 8765;

/**
 * 处理端口冲突：检测默认端口是否被占用，若被占用弹对话框让用户选择。
 * 返回最终决定使用的端口；返回 0 表示用户选择退出。
 */
async function resolvePortConflict(): Promise<number> {
  if (!isPortInUse(DEFAULT_PORT)) {
    return DEFAULT_PORT;
  }

  // 端口被占用，查询占用进程
  const proc = getProcessUsingPort(DEFAULT_PORT);
  const procDesc = proc
    ? `进程 PID=${proc.pid}${proc.name ? `（${proc.name}）` : ''}\n${proc.command || ''}`
    : '（无法获取占用进程信息）';

  const options: Electron.MessageBoxOptions = {
    type: 'warning',
    title: '端口被占用',
    message: `默认端口 ${DEFAULT_PORT} 已被占用`,
    detail: `占用进程：\n${procDesc}\n\n请选择如何处理：`,
    buttons: [
      '自动换用其他端口（推荐）',
      '结束占用进程后使用默认端口',
      '退出应用',
    ],
    defaultId: 0,
    cancelId: 2,
  };

  // 需要在 app ready 后才能弹对话框
  const choice: number = await dialog.showMessageBox(options).then((r) => r.response);

  if (choice === 2) {
    // 退出
    return 0;
  }

  if (choice === 1) {
    // 结束占用进程
    if (proc) {
      const killed = killProcess(proc.pid);
      if (!killed) {
        await dialog.showMessageBox({
          type: 'error',
          title: '无法结束进程',
          message: `无法结束进程 PID=${proc.pid}`,
          detail: '可能是权限不足。请手动结束该进程后重试，或选择换用其他端口。',
          buttons: ['知道了'],
        });
        return 0;
      }
      // 等待端口释放
      const freed = await waitForPortFree(DEFAULT_PORT, 5000);
      if (!freed) {
        await dialog.showMessageBox({
          type: 'warning',
          title: '端口未释放',
          message: `进程已结束，但端口 ${DEFAULT_PORT} 仍未释放`,
          detail: '端口可能处于 TIME_WAIT 状态，将自动换用其他端口。',
          buttons: ['知道了'],
        });
        return findFreePort(DEFAULT_PORT + 1);
      }
      return DEFAULT_PORT;
    }
    // 无进程信息，无法 kill，回退到换端口
    return findFreePort(DEFAULT_PORT + 1);
  }

  // choice === 0：换端口
  const newPort = findFreePort(DEFAULT_PORT + 1);
  await dialog.showMessageBox({
    type: 'info',
    title: '已选择新端口',
    message: `将使用端口 ${newPort}`,
    detail: `原端口 ${DEFAULT_PORT} 被占用，已自动选择空闲端口 ${newPort}。`,
    buttons: ['知道了'],
  });
  return newPort;
}

// 应用启动入口：先处理端口冲突 → 启动 Python 后端 → 创建窗口
async function bootstrap(): Promise<void> {
  // 1. 检测端口冲突
  const port = await resolvePortConflict();
  if (port === 0) {
    // 用户选择退出
    app.quit();
    return;
  }

  // 2. 启动后端
  try {
    backendPort = await startPythonBackend(port);
    console.log(`[main] Python 后端就绪，端口=${backendPort}`);
    backendError = null;
  } catch (err) {
    // 后端启动失败时记录错误，仍尝试用默认端口加载前端以便调试
    const msg = err instanceof Error ? err.message : String(err);
    backendError = msg;
    console.error('[main] Python 后端启动失败:', msg);
  }
  createWindow();
}

// 创建主窗口
function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 1000,
    minHeight: 700,
    title: '南美外贸微信智能助手',
    backgroundColor: '#F5F5F5',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // 通过附加参数把后端端口传给 preload
      additionalArguments: [
        `--backend-port=${backendPort}`,
        `--backend-error=${backendError ? encodeURIComponent(backendError) : ''}`,
      ],
    },
  });

  // 开发态加载 Vite dev server，生产态加载打包后的 index.html
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  // 外部链接用系统默认浏览器打开，避免在应用内打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  bootstrap();
});

// 所有窗口关闭时退出（macOS 除外，遵循平台习惯）
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// macOS 点击 dock 图标时重新创建窗口
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// 退出前清理 Python 子进程
app.on('before-quit', () => {
  stopPythonBackend();
});
