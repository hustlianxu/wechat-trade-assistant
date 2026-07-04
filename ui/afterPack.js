// electron-builder afterPack 钩子：打包后修复 extraResources 中可执行文件的权限。
//
// 根因：electron-builder 的 extraResources 复制文件时不保留 Unix 执行权限位，
// 导致 PyInstaller 产出的 wta-backend、bin/ 下的 whisper-cli、silk_decoder 等
// 在 .app 内丢失 +x，spawn 时报 EACCES。
//
// 本脚本在 electron-builder 产出 .app 后、生成 dmg/zip 前，对 backend-runtime/
// 和 bin/ 下的所有文件设置 0o755 权限（仅 macOS/Linux，Windows 跳过）。

const fs = require('fs');
const path = require('path');

/**
 * 递归设置目录下所有文件的权限为指定 mode。
 */
function chmodRecursive(dir, mode) {
  if (!fs.existsSync(dir)) return 0;
  let count = 0;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      fs.chmodSync(fullPath, mode);
      count++;
      count += chmodRecursive(fullPath, mode);
    } else if (entry.isFile()) {
      fs.chmodSync(fullPath, mode);
      count++;
    }
  }
  return count;
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

  // 修复 backend-runtime/ 下所有文件的权限（wta-backend + _internal/ 中的 .so 等）
  const runtimeDir = path.join(resourcesDir, 'backend-runtime');
  if (fs.existsSync(runtimeDir)) {
    const n = chmodRecursive(runtimeDir, 0o755);
    console.log(`[afterPack] 已设置 backend-runtime/ 权限（${n} 个文件/目录）`);

    // 确保主入口可执行
    const main = path.join(runtimeDir, 'wta-backend');
    if (fs.existsSync(main)) {
      fs.chmodSync(main, 0o755);
      console.log('[afterPack] wta-backend 权限已确认 0o755');
    }
  } else {
    console.log('[afterPack] 警告：backend-runtime 不存在，后端可能未打包');
  }

  // 修复 bin/ 下的原生二进制权限（whisper-cli, silk_decoder 等）
  const binDir = path.join(resourcesDir, 'bin');
  if (fs.existsSync(binDir)) {
    const n = chmodRecursive(binDir, 0o755);
    console.log(`[afterPack] 已设置 bin/ 权限（${n} 个文件/目录）`);
  }
};
