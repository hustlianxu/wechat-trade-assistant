import { spawn, ChildProcess } from 'child_process';
import * as path from 'path';
import { app } from 'electron';

// Python 后端子进程引用
let child: ChildProcess | null = null;

// 判断是否为打包后的生产环境
function isProduction(): boolean {
  return app.isPackaged;
}

// 解析后端启动命令
// 生产态：使用 PyInstaller 打包的 wta-backend 可执行文件
// 开发态：使用系统 python -m backend.main
function resolvePythonEnv(): { command: string; args: string[]; cwd: string; env: NodeJS.ProcessEnv } {
  if (isProduction()) {
    // 打包后资源根：process.resourcesPath
    // 目录布局（由 installers/ 脚本 + electron-builder 产出）：
    //   resources/
    //     backend-runtime/  ← PyInstaller 产出的 wta-backend 可执行文件 + 依赖
    //       wta-backend         (macOS/Linux)
    //       wta-backend.exe     (Windows)
    //       _internal/          (依赖库)
    //       backend/            (backend 包源码 + schema.sql)
    //     models/          ← whisper.cpp + Intento 模型（可选，按需下载）
    //     bin/             ← whisper-cli / silk_decoder 等原生二进制
    const resources = process.resourcesPath;
    const runtimeDir = path.join(resources, 'backend-runtime');
    const modelsDir = path.join(resources, 'models');
    const binDir = path.join(resources, 'bin');

    const command = process.platform === 'win32'
      ? path.join(runtimeDir, 'wta-backend.exe')
      : path.join(runtimeDir, 'wta-backend');

    // 打包后的可执行文件无需额外参数，自身即为入口
    const args: string[] = [];
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      // 让 backend 能找到随包资源
      WTA_MODELS_DIR: modelsDir,
      WTA_BIN_DIR: binDir,
      PYTHONUNBUFFERED: '1',
    };
    return { command, args, cwd: runtimeDir, env };
  }

  // 开发态
  const cwd = path.resolve(__dirname, '..', '..', 'src');
  return {
    command: process.platform === 'win32' ? 'python' : 'python3',
    args: ['-m', 'backend.main'],
    cwd,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  };
}

// 启动 Python 后端子进程，解析 stdout 中的 READY:<port> 行
// 超时 30 秒未就绪则 reject
export function startPythonBackend(): Promise<number> {
  return new Promise((resolve, reject) => {
    const { command, args, cwd, env } = resolvePythonEnv();
    console.log(`[python] 启动: ${command} ${args.join(' ')} (cwd=${cwd}, production=${isProduction()})`);

    child = spawn(command, args, { cwd, env });

    let resolved = false;

    // 30 秒超时保护
    const timer = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error('Python 后端 30 秒内未就绪（未收到 READY 行）'));
        stopPythonBackend();
      }
    }, 30000);

    // 监听 stdout，逐行查找匹配 /^READY:(\d+)$/ 的行
    child.stdout?.on('data', (data: Buffer) => {
      const text = data.toString();
      process.stdout.write(`[python] ${text}`);
      text.split(/\r?\n/).forEach((line) => {
        const m = line.match(/^READY:(\d+)$/);
        if (m && !resolved) {
          resolved = true;
          clearTimeout(timer);
          resolve(parseInt(m[1], 10));
        }
      });
    });

    // 打印 stderr 便于排错
    child.stderr?.on('data', (data: Buffer) => {
      process.stderr.write(`[python:err] ${data.toString()}`);
    });

    // 子进程异常退出时若尚未就绪则 reject
    child.on('exit', (code) => {
      console.log(`[python] 子进程退出，code=${code}`);
      child = null;
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        reject(new Error(`Python 后端进程意外退出，code=${code}`));
      }
    });

    child.on('error', (err) => {
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        reject(new Error(`无法启动 Python 进程: ${err.message}`));
      }
    });
  });
}

// 终止 Python 后端子进程
export function stopPythonBackend(): void {
  if (child) {
    try {
      child.kill();
    } catch (e) {
      console.error('[python] kill 失败:', e);
    }
    child = null;
  }
}
