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

// 在系统中查找可用的 Python 可执行文件
function findPythonBinary(): string | null {
  const candidates: string[] = [];
  if (process.platform === 'win32') {
    candidates.push('python', 'python3', 'py');
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
      if (path.isAbsolute(cmd) && !fs.existsSync(cmd)) continue;
      execFileSync(cmd, ['--version'], { stdio: 'pipe', timeout: 3000 });
      return cmd;
    } catch {
      // 继续尝试下一个
    }
  }
  return null;
}

// 递归设置目录下所有文件的可执行权限
function chmodRecursive(dir: string, mode: number): void {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    try {
      fs.chmodSync(fullPath, mode);
      if (entry.isDirectory()) {
        chmodRecursive(fullPath, mode);
      }
    } catch {
      // 忽略个别文件权限设置失败
    }
  }
}

// 生产态：解析 PyInstaller 产出的后端可执行文件路径
function resolveProductionEnv(): {
  command: string;
  args: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  runtimeDir: string;
} {
  const resources = process.resourcesPath;
  const runtimeDir = path.join(resources, 'backend-runtime');
  const modelsDir = path.join(resources, 'models');
  const binDir = path.join(resources, 'bin');

  const command = process.platform === 'win32'
    ? path.join(runtimeDir, 'wta-backend.exe')
    : path.join(runtimeDir, 'wta-backend');

  return {
    command,
    args: [],
    cwd: runtimeDir,
    env: {
      ...process.env,
      WTA_MODELS_DIR: modelsDir,
      WTA_BIN_DIR: binDir,
      PYTHONUNBUFFERED: '1',
    },
    runtimeDir,
  };
}

// 开发态：用系统 Python 运行 backend.main
function resolveDevEnv(): { command: string; args: string[]; cwd: string; env: NodeJS.ProcessEnv } {
  const cwd = path.resolve(__dirname, '..', '..', 'src');
  const pythonBin = findPythonBinary() || (process.platform === 'win32' ? 'python' : 'python3');
  return {
    command: pythonBin,
    args: ['-m', 'backend.main'],
    cwd,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  };
}

// 确保文件有执行权限（macOS/Linux）
function ensureExecutable(filePath: string): boolean {
  if (process.platform === 'win32') return true;
  try {
    if (!fs.existsSync(filePath)) return false;
    const stat = fs.statSync(filePath);
    // 检查当前权限是否已有 owner execute
    const hasExec = (stat.mode & 0o100) !== 0;
    if (!hasExec) {
      fs.chmodSync(filePath, 0o755);
    }
    return true;
  } catch (e) {
    console.warn(`[python] chmod ${filePath} 失败:`, e);
    return false;
  }
}

// 尝试 spawn 子进程，返回进程或抛出错误
function spawnBackend(
  command: string,
  args: string[],
  cwd: string,
  env: NodeJS.ProcessEnv,
): ChildProcess {
  return spawn(command, args, { cwd, env });
}

// 启动 Python 后端子进程，解析 stdout 中的 READY:<port> 行
// preferredPort: 期望端口（通过 WTA_PORT 环境变量传给后端）
export function startPythonBackend(preferredPort?: number): Promise<number> {
  return new Promise((resolve, reject) => {
    let command: string;
    let args: string[];
    let cwd: string;
    let env: NodeJS.ProcessEnv;
    let runtimeDir = '';

    if (isProduction()) {
      const prod = resolveProductionEnv();
      command = prod.command;
      args = prod.args;
      cwd = prod.cwd;
      env = prod.env;
      runtimeDir = prod.runtimeDir;
    } else {
      const dev = resolveDevEnv();
      command = dev.command;
      args = dev.args;
      cwd = dev.cwd;
      env = dev.env;
    }

    if (preferredPort && !env.WTA_PORT) {
      env.WTA_PORT = String(preferredPort);
    }

    // macOS/Linux: 确保可执行文件有 +x 权限
    // electron-builder 的 extraResources 复制时不保留执行权限位，
    // 即使有 afterPack 脚本，这里也做双保险。
    if (process.platform !== 'win32') {
      ensureExecutable(command);
      // 同时修复 bin/ 下的原生二进制
      const binDir = env.WTA_BIN_DIR;
      if (binDir && fs.existsSync(binDir)) {
        chmodRecursive(binDir, 0o755);
      }
      // 修复 _internal/ 下的 .so 等动态库权限
      if (runtimeDir) {
        const internalDir = path.join(runtimeDir, '_internal');
        if (fs.existsSync(internalDir)) {
          chmodRecursive(internalDir, 0o755);
        }
      }
    }

    console.log(`[python] 启动: ${command} ${args.join(' ')} (cwd=${cwd}, production=${isProduction()}, port=${preferredPort || 'default'})`);

    let childProc: ChildProcess;
    try {
      childProc = spawnBackend(command, args, cwd, env);
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

    childProc.stderr?.on('data', (data: Buffer) => {
      const text = data.toString();
      process.stderr.write(`[python:err] ${text}`);
      stderrBuffer.push(text);
    });

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
      console.error('[python] spawn error:', err);
      if (!resolved) {
        resolved = true;
        clearTimeout(timer);

        // EACCES 时给出详细的诊断信息
        if (err.message.includes('EACCES')) {
          let detail = `无法启动 Python 进程: ${err.message}\n`;
          detail += `\n诊断信息:\n`;
          detail += `  命令: ${command}\n`;
          detail += `  存在: ${fs.existsSync(command) ? '是' : '否'}\n`;
          if (fs.existsSync(command)) {
            try {
              const stat = fs.statSync(command);
              detail += `  权限: ${stat.mode.toString(8)}\n`;
            } catch {}
          }
          detail += `  运行目录: ${cwd}\n`;
          detail += `  平台: ${process.platform} ${process.arch}\n`;
          detail += `\n请尝试:\n`;
          detail += `  1. 终端执行: chmod +x "${command}"\n`;
          detail += `  2. 或重新打包（afterPack 脚本会自动设置权限）\n`;
          detail += `  3. macOS 可能需要: sudo xattr -rd com.apple.quarantine "/Applications/WeChat Trade Assistant.app"`;
          reject(new Error(detail));
        } else {
          reject(new Error(`无法启动 Python 进程: ${err.message}`));
        }
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
