import { spawn, ChildProcess, execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { app } from 'electron';

// Python 后端子进程引用
let child: ChildProcess | null = null;

// 判断是否为打包后的生产环境
function isProduction(): boolean {
  return app.isPackaged;
}

// 在系统中查找可用的 Python 可执行文件（dev 模式用）
function findPythonBinary(): string | null {
  const candidates: string[] = [];
  if (process.platform === 'win32') {
    candidates.push('python', 'python3', 'py');
    // 常见安装路径
    candidates.push('C:\\Python311\\python.exe', 'C:\\Python310\\python.exe', 'C:\\Python39\\python.exe');
    candidates.push(
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
    );
  } else {
    candidates.push('python3', 'python');
    // macOS 常见路径（Homebrew / pyenv / 系统自带）
    candidates.push('/usr/local/bin/python3', '/opt/homebrew/bin/python3', '/usr/bin/python3');
    candidates.push('/opt/homebrew/bin/python3.11', '/opt/homebrew/bin/python3.10');
    candidates.push(path.join(process.env.HOME || '', '.pyenv', 'shims', 'python3'));
  }
  for (const cmd of candidates) {
    try {
      // 如果是绝对路径且文件不存在，跳过
      if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) continue;
      execFileSync(cmd, ['--version'], { stdio: 'pipe', timeout: 3000 });
      return cmd;
    } catch {
      // 继续尝试下一个
    }
  }
  return null;
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

  // 开发态：从 src/ 目录运行 backend.main
  const cwd = path.resolve(__dirname, '..', '..', 'src');
  const pythonBin = findPythonBinary() || (process.platform === 'win32' ? 'python' : 'python3');
  return {
    command: pythonBin,
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

    let childProc: ChildProcess;
    try {
      childProc = spawn(command, args, { cwd, env });
    } catch (err) {
      reject(new Error(`无法 spawn Python 进程: ${err}`));
      return;
    }
    child = childProc;

    let resolved = false;
    const stderrBuffer: string[] = [];

    // 30 秒超时保护
    const timer = setTimeout(() => {
      if (!resolved) {
        resolved = true;
        reject(new Error('Python 后端 30 秒内未就绪（未收到 READY 行）'));
        stopPythonBackend();
      }
    }, 30000);

    // 监听 stdout，逐行查找匹配 /^READY:(\d+)$/ 的行
    childProc.stdout?.on('data', (data: Buffer) => {
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
    childProc.stderr?.on('data', (data: Buffer) => {
      const text = data.toString();
      process.stderr.write(`[python:err] ${text}`);
      stderrBuffer.push(text);
    });

    // 子进程异常退出时若尚未就绪则 reject
    childProc.on('exit', (code) => {
      console.log(`[python] 子进程退出，code=${code}`);
      child = null;
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);
        const errTail = stderrBuffer.slice(-10).join('');
        reject(new Error(`Python 后端进程意外退出，code=${code}\n${errTail}`));
      }
    });

    childProc.on('error', (err) => {
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
