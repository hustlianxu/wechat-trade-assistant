import { contextBridge, shell } from 'electron';

// 从 additionalArguments 中解析后端端口，未传入时回退到默认 8765
const portArg = process.argv.find((a) => a.startsWith('--backend-port='));
const port = portArg ? portArg.split('=')[1] : '8765';

// 通过 contextBridge 安全地暴露最小 API 给渲染进程
contextBridge.exposeInMainWorld('api', {
  // 后端 REST API 基地址（含端口）
  apiUrl: `http://127.0.0.1:${port}`,
  // 用系统默认浏览器打开外部链接
  openExternal: (url: string) => shell.openExternal(url),
});
