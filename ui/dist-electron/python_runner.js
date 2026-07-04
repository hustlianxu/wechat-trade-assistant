"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.startPythonBackend = startPythonBackend;
exports.stopPythonBackend = stopPythonBackend;
const child_process_1 = require("child_process");
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const electron_1 = require("electron");
// Python 后端子进程引用
let child = null;
// 判断是否为打包后的生产环境
function isProduction() {
    return electron_1.app.isPackaged;
}
// 在系统中查找可用的 Python 可执行文件（dev 模式用）
function findPythonBinary() {
    const candidates = [];
    if (process.platform === 'win32') {
        candidates.push('python', 'python3', 'py');
        // 常见安装路径
        candidates.push('C:\\Python311\\python.exe', 'C:\\Python310\\python.exe', 'C:\\Python39\\python.exe');
        candidates.push(path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'), path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'));
    }
    else {
        candidates.push('python3', 'python');
        // macOS 常见路径（Homebrew / pyenv / 系统自带）
        candidates.push('/usr/local/bin/python3', '/opt/homebrew/bin/python3', '/usr/bin/python3');
        candidates.push('/opt/homebrew/bin/python3.11', '/opt/homebrew/bin/python3.10');
        candidates.push(path.join(process.env.HOME || '', '.pyenv', 'shims', 'python3'));
    }
    for (const cmd of candidates) {
        try {
            // 如果是绝对路径且文件不存在，跳过
            if (path.isAbsolute(cmd) && !fs.existsSync(cmd))
                continue;
            (0, child_process_1.execFileSync)(cmd, ['--version'], { stdio: 'pipe', timeout: 3000 });
            return cmd;
        }
        catch {
            // 继续尝试下一个
        }
    }
    return null;
}
// 解析后端启动命令
// 生产态：使用 PyInstaller 打包的 wta-backend 可执行文件
// 开发态：使用系统 python -m backend.main
function resolvePythonEnv() {
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
        const args = [];
        const env = {
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
// preferredPort: 期望端口（通过 WTA_PORT 环境变量传给后端）
function startPythonBackend(preferredPort) {
    return new Promise((resolve, reject) => {
        const { command, args, cwd, env } = resolvePythonEnv();
        // 通过 WTA_PORT 指定后端监听端口（后端 main.py 读取此环境变量）
        if (preferredPort && !env.WTA_PORT) {
            env.WTA_PORT = String(preferredPort);
        }
        // macOS/Linux: 打包后的 PyInstaller 可执行文件在 electron-builder 打包后
        // 可能丢失执行权限位，spawn 时会报 EACCES。spawn 前补上执行权限。
        if (process.platform !== 'win32') {
            try {
                if (fs.existsSync(command)) {
                    fs.chmodSync(command, 0o755);
                }
            }
            catch (e) {
                console.warn(`[python] chmod ${command} 失败:`, e);
            }
        }
        console.log(`[python] 启动: ${command} ${args.join(' ')} (cwd=${cwd}, production=${isProduction()}, port=${preferredPort || 'default'})`);
        let childProc;
        try {
            childProc = (0, child_process_1.spawn)(command, args, { cwd, env });
        }
        catch (err) {
            reject(new Error(`无法 spawn Python 进程: ${err}`));
            return;
        }
        child = childProc;
        let resolved = false;
        const stderrBuffer = [];
        // 30 秒超时保护
        const timer = setTimeout(() => {
            if (!resolved) {
                resolved = true;
                reject(new Error('Python 后端 30 秒内未就绪（未收到 READY 行）'));
                stopPythonBackend();
            }
        }, 30000);
        // 监听 stdout，逐行查找匹配 /^READY:(\d+)$/ 的行
        childProc.stdout?.on('data', (data) => {
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
        childProc.stderr?.on('data', (data) => {
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
function stopPythonBackend() {
    if (child) {
        try {
            child.kill();
        }
        catch (e) {
            console.error('[python] kill 失败:', e);
        }
        child = null;
    }
}
