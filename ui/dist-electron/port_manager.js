"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.isPortInUse = isPortInUse;
exports.getProcessUsingPort = getProcessUsingPort;
exports.killProcess = killProcess;
exports.findFreePort = findFreePort;
exports.waitForPortFree = waitForPortFree;
const child_process_1 = require("child_process");
/**
 * 检测指定端口是否被监听占用。
 */
function isPortInUse(port) {
    try {
        if (process.platform === 'win32') {
            // Windows: netstat -ano -p tcp，找 LISTENING 且端口匹配的行
            const out = (0, child_process_1.execFileSync)('netstat', ['-ano', '-p', 'tcp'], {
                encoding: 'utf8',
                timeout: 5000,
                stdio: ['pipe', 'pipe', 'pipe'],
            });
            return out
                .split(/\r?\n/)
                .some((line) => {
                const cols = line.trim().split(/\s+/);
                // TCP    127.0.0.1:8765    0.0.0.0:0    LISTENING    1234
                return (cols.length >= 5 &&
                    cols[1] && cols[1].endsWith(`:${port}`) &&
                    cols[3] === 'LISTENING');
            });
        }
        // macOS/Linux: lsof -i :PORT -sTCP:LISTEN
        // 退出码 0 且有输出 → 占用；退出码 1 → 空闲
        const out = (0, child_process_1.execFileSync)('lsof', ['-i', `:${port}`, '-sTCP:LISTEN', '-t'], {
            encoding: 'utf8',
            timeout: 5000,
            stdio: ['pipe', 'pipe', 'pipe'],
        });
        return out.trim().length > 0;
    }
    catch (e) {
        // lsof 无匹配返回退出码 1，视为端口空闲
        const err = e;
        if (process.platform !== 'win32' && err.status === 1)
            return false;
        return false;
    }
}
/**
 * 查询占用指定端口的进程信息（PID + 名称 + 命令行）。
 * 返回 null 表示未找到或查询失败。
 */
function getProcessUsingPort(port) {
    try {
        if (process.platform === 'win32') {
            const out = (0, child_process_1.execFileSync)('netstat', ['-ano', '-p', 'tcp'], {
                encoding: 'utf8',
                timeout: 5000,
                stdio: ['pipe', 'pipe', 'pipe'],
            });
            let pid = 0;
            for (const line of out.split(/\r?\n/)) {
                const cols = line.trim().split(/\s+/);
                if (cols.length >= 5 &&
                    cols[1] && cols[1].endsWith(`:${port}`) &&
                    cols[3] === 'LISTENING') {
                    pid = parseInt(cols[4], 10);
                    if (!Number.isNaN(pid))
                        break;
                }
            }
            if (!pid)
                return null;
            let name = '';
            let command = '';
            try {
                const taskOut = (0, child_process_1.execFileSync)('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], { encoding: 'utf8', timeout: 5000, stdio: ['pipe', 'pipe', 'pipe'] }).trim();
                // "WeChat.exe","1234","Console","1","50,000 K"
                const firstCol = taskOut.split('","')[0];
                name = firstCol.replace(/^"/, '');
                command = taskOut;
            }
            catch {
                // 忽略
            }
            return { pid, name, command };
        }
        // macOS/Linux
        const out = (0, child_process_1.execFileSync)('lsof', ['-i', `:${port}`, '-sTCP:LISTEN', '-t'], {
            encoding: 'utf8',
            timeout: 5000,
            stdio: ['pipe', 'pipe', 'pipe'],
        }).trim();
        if (!out)
            return null;
        const pid = parseInt(out.split('\n')[0], 10);
        if (Number.isNaN(pid))
            return null;
        let name = '';
        let command = '';
        try {
            name = (0, child_process_1.execFileSync)('ps', ['-p', String(pid), '-o', 'comm='], {
                encoding: 'utf8', timeout: 3000, stdio: ['pipe', 'pipe', 'pipe'],
            }).trim();
        }
        catch { /* 忽略 */ }
        try {
            command = (0, child_process_1.execFileSync)('ps', ['-p', String(pid), '-o', 'command='], {
                encoding: 'utf8', timeout: 3000, stdio: ['pipe', 'pipe', 'pipe'],
            }).trim();
        }
        catch { /* 忽略 */ }
        return { pid, name, command };
    }
    catch {
        return null;
    }
}
/**
 * 强制杀死指定 PID 的进程。返回是否成功。
 */
function killProcess(pid) {
    try {
        if (process.platform === 'win32') {
            (0, child_process_1.execFileSync)('taskkill', ['/PID', String(pid), '/F'], {
                stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000,
            });
        }
        else {
            (0, child_process_1.execFileSync)('kill', ['-9', String(pid)], {
                stdio: ['pipe', 'pipe', 'pipe'], timeout: 5000,
            });
        }
        return true;
    }
    catch {
        return false;
    }
}
/**
 * 从 startPort 开始向上寻找一个空闲端口，最多尝试 maxAttempts 个。
 */
function findFreePort(startPort, maxAttempts = 100) {
    for (let p = startPort; p < startPort + maxAttempts; p++) {
        if (!isPortInUse(p))
            return p;
    }
    return startPort + maxAttempts;
}
/**
 * 等待端口释放（杀进程后端口可能仍处于 TIME_WAIT）。
 */
function waitForPortFree(port, timeoutMs = 5000) {
    const start = Date.now();
    return new Promise((resolve) => {
        const check = () => {
            if (!isPortInUse(port)) {
                resolve(true);
                return;
            }
            if (Date.now() - start > timeoutMs) {
                resolve(false);
                return;
            }
            setTimeout(check, 200);
        };
        check();
    });
}
