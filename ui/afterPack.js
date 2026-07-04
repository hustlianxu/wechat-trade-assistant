// electron-builder afterPack 钩子：打包后修复 extraResources 中可执行文件的权限。
//
// 根因 1：electron-builder 的 extraResources 复制文件时不保留 Unix 执行权限位。
// 根因 2：PyInstaller COLLECT 模式产出结构是 dist-python/wta-backend/wta-backend
//         （目录套可执行文件），复制后变成 backend-runtime/wta-backend/wta-backend。
//         若误把目录当成可执行文件 spawn，会报 EACCES。
//
// 本脚本在 electron-builder 产出 .app 后、生成 dmg/zip 前：
// 1. 递归设置 backend-runtime/ 和 bin/ 下所有文件的 0o755 权限
// 2. 特别确保 wta-backend 可执行文件（无论嵌套在哪层）有 +x
// 仅 macOS/Linux 需要，Windows 跳过。

const fs = require('fs');
const path = require('path');

/**
 * 递归设置目录下所有文件的权限为指定 mode。
 * 返回处理的文件/目录数量。
 */
function chmodRecursive(dir, mode) {
  if (!fs.existsSync(dir)) return 0;
  let count = 0;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    try {
      fs.chmodSync(fullPath, mode);
      count++;
      if (entry.isDirectory()) {
        count += chmodRecursive(fullPath, mode);
      }
    } catch (e) {
      console.warn(`[afterPack] chmod 失败: ${fullPath}`, e.message);
    }
  }
  return count;
}

/**
 * 在 runtimeDir 下递归查找名为 wta-backend（或 wta-backend.exe）的可执行文件。
 * PyInstaller COLLECT 模式下，可执行文件在 wta-backend/wta-backend 子目录。
 */
function findExecutable(dir, exeNames, depth = 0, maxDepth = 4) {
  if (depth > maxDepth || !fs.existsSync(dir)) return null;
  for (const name of exeNames) {
    const candidate = path.join(dir, name);
    if (fs.existsSync(candidate)) {
      try {
        const stat = fs.statSync(candidate);
        if (stat.isFile()) return candidate;
      } catch {}
    }
  }
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    // 跳过明显的依赖目录，加速查找
    if (['node_modules', '__pycache__'].includes(entry.name)) continue;
    const found = findExecutable(path.join(dir, entry.name), exeNames, depth + 1, maxDepth);
    if (found) return found;
  }
  return null;
}

exports.default = async function (context) {
  // Windows 不需要 chmod
  if (context.electronPlatformName === 'win32') {
    return;
  }

  // appOutDir:
  //   macOS: <dist>/<AppName>.app
  //   Linux: <dist>/<AppName>
  const appOutDir = context.appOutDir;

  // Resources 目录：
  //   macOS: <AppName>.app/Contents/Resources/
  //   Linux: <AppName>/resources/
  let resourcesDir;
  if (context.electronPlatformName === 'darwin') {
    resourcesDir = path.join(appOutDir, 'Contents', 'Resources');
  } else {
    resourcesDir = path.join(appOutDir, 'resources');
  }

  if (!fs.existsSync(resourcesDir)) {
    console.log('[afterPack] Resources 目录不存在，跳过:', resourcesDir);
    return;
  }

  const exeNames = context.electronPlatformName === 'win32'
    ? ['wta-backend.exe']
    : ['wta-backend'];

  // 1. 修复 backend-runtime/ 下所有文件的权限
  const runtimeDir = path.join(resourcesDir, 'backend-runtime');
  if (fs.existsSync(runtimeDir)) {
    const n = chmodRecursive(runtimeDir, 0o755);
    console.log(`[afterPack] 已设置 backend-runtime/ 权限（${n} 个文件/目录）`);

    // 2. 特别确保 wta-backend 可执行文件有 +x
    const exe = findExecutable(runtimeDir, exeNames);
    if (exe) {
      fs.chmodSync(exe, 0o755);
      console.log(`[afterPack] 后端可执行文件权限已确认 0o755: ${exe}`);
    } else {
      console.error('[afterPack] 警告：未在 backend-runtime/ 下找到 wta-backend 可执行文件！');
      console.error('[afterPack] backend-runtime 目录结构:');
      try {
        const list = fs.readdirSync(runtimeDir);
        console.error(`  ${runtimeDir}/`);
        for (const item of list.slice(0, 20)) {
          const itemPath = path.join(runtimeDir, item);
          const isDir = fs.statSync(itemPath).isDirectory();
          console.error(`    ${item}${isDir ? '/' : ''}`);
          if (isDir && item === 'wta-backend') {
            const subList = fs.readdirSync(itemPath);
            for (const sub of subList.slice(0, 20)) {
              console.error(`      ${sub}`);
            }
          }
        }
      } catch (e) {
        console.error('  无法列出目录:', e.message);
      }
    }
  } else {
    console.log('[afterPack] 警告：backend-runtime 不存在，后端可能未打包');
  }

  // 3. 修复 bin/ 下的原生二进制权限（whisper-cli, silk_decoder 等）
  const binDir = path.join(resourcesDir, 'bin');
  if (fs.existsSync(binDir)) {
    const n = chmodRecursive(binDir, 0o755);
    console.log(`[afterPack] 已设置 bin/ 权限（${n} 个文件/目录）`);
  }
};
