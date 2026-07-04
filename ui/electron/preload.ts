import { contextBridge, shell } from 'electron';

// 从 additionalArguments 中解析后端端口与启动错误，未传入时回退到默认值
const portArg = process.argv.find((a) => a.startsWith('--backend-port='));
const port = portArg ? portArg.split('=')[1] : '8765';

const errArg = process.argv.find((a) => a.startsWith('--backend-error='));
const startupError = errArg ? decodeURIComponent(errArg.split('=')[1] || '') : '';

// 通过 contextBridge 安全地暴露最小 API 给渲染进程
contextBridge.exposeInMainWorld('api', {
  // 后端 REST API 基地址（含端口）
  apiUrl: `http://127.0.0.1:${port}`,
  // 后端启动错误（为空表示无错误）
  backendError: startupError,
  // 用系统默认浏览器打开外部链接
  openExternal: (url: string) => shell.openExternal(url),
});
