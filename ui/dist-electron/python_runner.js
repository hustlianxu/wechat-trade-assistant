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
// 在系统中查找可用的 Python 可执行文件
function findPythonBinary() {
    const candidates = [];
    if (process.platform === 'win32') {
        candidates.push('python', 'python3', 'py');
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
// 递归设置目录下所有文件的可执行权限
function chmodRecursive(dir, mode) {
    if (!fs.existsSync(dir))
        return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const fullPath = path.join(dir, entry.name);
        try {
            fs.chmodSync(fullPath, mode);
            if (entry.isDirectory()) {
                chmodRecursive(fullPath, mode);
            }
        }
        catch {
            // 忽略个别文件权限设置失败
        }
    }
}
// 生产态：解析 PyInstaller 产出的后端可执行文件路径
// PyInstaller COLLECT 模式产出结构：
//   dist-python/wta-backend/wta-backend       (macOS/Linux 可执行文件)
//   dist-python/wta-backend/_internal/        (依赖)
// electron-builder extraResources 把 dist-python 复制为 backend-runtime，因此实际：
//   backend-runtime/wta-backend/wta-backend   ← 真正的可执行文件
// 但若用户用 --onedir 根目录或自定义布局，也可能直接是 backend-runtime/wta-backend。
// 本函数智能探测：优先找文件，其次找目录下的同名可执行文件。
function resolveProductionEnv() {
    const resources = process.resourcesPath;
    const runtimeDir = path.join(resources, 'backend-runtime');
    const modelsDir = path.join(resources, 'models');
    const binDir = path.join(resources, 'bin');
    const exeName = process.platform === 'win32' ? 'wta-backend.exe' : 'wta-backend';
    const directPath = path.join(runtimeDir, exeName);
    const nestedPath = path.join(runtimeDir, 'wta-backend', exeName);
    let command;
    // 优先：directPath 是文件（非目录）→ 直接用
    if (fs.existsSync(directPath) && fs.statSync(directPath).isFile()) {
        command = directPath;
    }
    else if (fs.existsSync(nestedPath) && fs.statSync(nestedPath).isFile()) {
        // 其次：PyInstaller COLLECT 嵌套结构 wta-backend/wta-backend
        command = nestedPath;
    }
    else {
        // 兜底：扫描 runtimeDir 下任意位置找 wta-backend 可执行文件
        let found = null;
        function scanDir(dir, depth) {
            if (found || depth > 3 || !fs.existsSync(dir))
                return;
            for (const name of fs.readdirSync(dir)) {
                const full = path.join(dir, name);
                try {
                    const stat = fs.statSync(full);
                    if (stat.isFile() && name === exeName) {
                        found = full;
                        return;
                    }
                    if (stat.isDirectory() && !name.startsWith('.')) {
                        scanDir(full, depth + 1);
                    }
                }
                catch {
                    // 忽略权限错误
                }
            }
        }
        scanDir(runtimeDir, 0);
        command = found || nestedPath; // 找不到仍用 nestedPath 让报错信息可读
    }
    // cwd 设为可执行文件所在目录，便于 PyInstaller 找到 _internal/
    const commandDir = path.dirname(command);
    return {
        command,
        args: [],
        cwd: commandDir,
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
function resolveDevEnv() {
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
function ensureExecutable(filePath) {
    if (process.platform === 'win32')
        return true;
    try {
        if (!fs.existsSync(filePath))
            return false;
        const stat = fs.statSync(filePath);
        // 关键：必须是文件，不能是目录。目录权限 0o755 不代表可执行
        if (stat.isDirectory()) {
            console.error(`[python] 路径是目录而非可执行文件: ${filePath}`);
            return false;
        }
        const hasExec = (stat.mode & 0o100) !== 0;
        if (!hasExec) {
            fs.chmodSync(filePath, 0o755);
        }
        return true;
    }
    catch (e) {
        console.warn(`[python] chmod ${filePath} 失败:`, e);
        return false;
    }
}
// 尝试 spawn 子进程，返回进程或抛出错误
function spawnBackend(command, args, cwd, env) {
    return (0, child_process_1.spawn)(command, args, { cwd, env });
}
// 启动 Python 后端子进程，解析 stdout 中的 READY:<port> 行
// preferredPort: 期望端口（通过 WTA_PORT 环境变量传给后端）
function startPythonBackend(preferredPort) {
    return new Promise((resolve, reject) => {
        let command;
        let args;
        let cwd;
        let env;
        let runtimeDir = '';
        if (isProduction()) {
            const prod = resolveProductionEnv();
            command = prod.command;
            args = prod.args;
            cwd = prod.cwd;
            env = prod.env;
            runtimeDir = prod.runtimeDir;
        }
        else {
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
        let childProc;
        try {
            childProc = spawnBackend(command, args, cwd, env);
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
        childProc.stderr?.on('data', (data) => {
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
                        }
                        catch { }
                    }
                    detail += `  运行目录: ${cwd}\n`;
                    detail += `  平台: ${process.platform} ${process.arch}\n`;
                    detail += `\n请尝试:\n`;
                    detail += `  1. 终端执行: chmod +x "${command}"\n`;
                    detail += `  2. 或重新打包（afterPack 脚本会自动设置权限）\n`;
                    detail += `  3. macOS 可能需要: sudo xattr -rd com.apple.quarantine "/Applications/WeChat Trade Assistant.app"`;
                    reject(new Error(detail));
                }
                else {
                    reject(new Error(`无法启动 Python 进程: ${err.message}`));
                }
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
