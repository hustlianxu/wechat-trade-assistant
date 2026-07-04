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
const electron_1 = require("electron");
const path = __importStar(require("path"));
const python_runner_1 = require("./python_runner");
const port_manager_1 = require("./port_manager");
// 主窗口引用，避免被垃圾回收
let mainWindow = null;
// 后端服务端口，由 python_runner 解析 READY 行得到，默认 8765
let backendPort = 8765;
// 后端启动错误信息（供前端查询）
let backendError = null;
// 默认端口
const DEFAULT_PORT = 8765;
/**
 * 处理端口冲突：检测默认端口是否被占用，若被占用弹对话框让用户选择。
 * 返回最终决定使用的端口；返回 0 表示用户选择退出。
 */
async function resolvePortConflict() {
    if (!(0, port_manager_1.isPortInUse)(DEFAULT_PORT)) {
        return DEFAULT_PORT;
    }
    // 端口被占用，查询占用进程
    const proc = (0, port_manager_1.getProcessUsingPort)(DEFAULT_PORT);
    const procDesc = proc
        ? `进程 PID=${proc.pid}${proc.name ? `（${proc.name}）` : ''}\n${proc.command || ''}`
        : '（无法获取占用进程信息）';
    const options = {
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
    const choice = await electron_1.dialog.showMessageBox(options).then((r) => r.response);
    if (choice === 2) {
        // 退出
        return 0;
    }
    if (choice === 1) {
        // 结束占用进程
        if (proc) {
            const killed = (0, port_manager_1.killProcess)(proc.pid);
            if (!killed) {
                await electron_1.dialog.showMessageBox({
                    type: 'error',
                    title: '无法结束进程',
                    message: `无法结束进程 PID=${proc.pid}`,
                    detail: '可能是权限不足。请手动结束该进程后重试，或选择换用其他端口。',
                    buttons: ['知道了'],
                });
                return 0;
            }
            // 等待端口释放
            const freed = await (0, port_manager_1.waitForPortFree)(DEFAULT_PORT, 5000);
            if (!freed) {
                await electron_1.dialog.showMessageBox({
                    type: 'warning',
                    title: '端口未释放',
                    message: `进程已结束，但端口 ${DEFAULT_PORT} 仍未释放`,
                    detail: '端口可能处于 TIME_WAIT 状态，将自动换用其他端口。',
                    buttons: ['知道了'],
                });
                return (0, port_manager_1.findFreePort)(DEFAULT_PORT + 1);
            }
            return DEFAULT_PORT;
        }
        // 无进程信息，无法 kill，回退到换端口
        return (0, port_manager_1.findFreePort)(DEFAULT_PORT + 1);
    }
    // choice === 0：换端口
    const newPort = (0, port_manager_1.findFreePort)(DEFAULT_PORT + 1);
    await electron_1.dialog.showMessageBox({
        type: 'info',
        title: '已选择新端口',
        message: `将使用端口 ${newPort}`,
        detail: `原端口 ${DEFAULT_PORT} 被占用，已自动选择空闲端口 ${newPort}。`,
        buttons: ['知道了'],
    });
    return newPort;
}
// 应用启动入口：先处理端口冲突 → 启动 Python 后端 → 创建窗口
async function bootstrap() {
    // 1. 检测端口冲突
    const port = await resolvePortConflict();
    if (port === 0) {
        // 用户选择退出
        electron_1.app.quit();
        return;
    }
    // 2. 启动后端
    try {
        backendPort = await (0, python_runner_1.startPythonBackend)(port);
        console.log(`[main] Python 后端就绪，端口=${backendPort}`);
        backendError = null;
    }
    catch (err) {
        // 后端启动失败时记录错误，仍尝试用默认端口加载前端以便调试
        const msg = err instanceof Error ? err.message : String(err);
        backendError = msg;
        console.error('[main] Python 后端启动失败:', msg);
    }
    createWindow();
}
// 创建主窗口
function createWindow() {
    mainWindow = new electron_1.BrowserWindow({
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
    }
    else {
        mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
    }
    // 外部链接用系统默认浏览器打开，避免在应用内打开
    mainWindow.webContents.setWindowOpenHandler(({ url }) => {
        electron_1.shell.openExternal(url);
        return { action: 'deny' };
    });
    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}
electron_1.app.whenReady().then(() => {
    bootstrap();
});
// 所有窗口关闭时退出（macOS 除外，遵循平台习惯）
electron_1.app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        electron_1.app.quit();
    }
});
// macOS 点击 dock 图标时重新创建窗口
electron_1.app.on('activate', () => {
    if (electron_1.BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});
// 退出前清理 Python 子进程
electron_1.app.on('before-quit', () => {
    (0, python_runner_1.stopPythonBackend)();
});
