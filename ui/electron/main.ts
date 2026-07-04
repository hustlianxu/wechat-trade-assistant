import { app, BrowserWindow, shell } from 'electron';
import * as path from 'path';
import { startPythonBackend, stopPythonBackend } from './python_runner';

// 主窗口引用，避免被垃圾回收
let mainWindow: BrowserWindow | null = null;

// 后端服务端口，由 python_runner 解析 READY 行得到，默认 8765
let backendPort: number = 8765;

// 应用启动入口：先启动 Python 后端，再创建窗口
async function bootstrap(): Promise<void> {
  try {
    // 等待后端就绪并解析端口
    backendPort = await startPythonBackend();
    console.log(`[main] Python 后端就绪，端口=${backendPort}`);
  } catch (err) {
    // 后端启动失败时打印错误，仍尝试用默认端口加载前端以便调试
    console.error('[main] Python 后端启动失败:', err);
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
      additionalArguments: [`--backend-port=${backendPort}`],
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
