#!/usr/bin/env bash
# macOS 打包脚本：构建 .dmg 安装包（同时支持 Apple Silicon 与 Intel）
#
# 前置条件：
#   - macOS 12+（建议 14+）
#   - Python 3.10+（建议用 python-build-standalone 或 pyenv 管理）
#   - Node.js 18+ 与 npm
#   - PyInstaller: pip install pyinstaller
#   - 可选：whisper.cpp 预编译二进制放入 bin/、模型放入 models/whisper/
#
# 用法：
#   cd <项目根>
#   bash installers/build_macos.sh            # 当前架构
#   ARCH=arm64 bash installers/build_macos.sh # 指定 arm64
#   ARCH=x64   bash installers/build_macos.sh # 指定 x64
#
# 产出：
#   ui/dist-electron/WeChat Trade Assistant-<version>-arm64.dmg
#   ui/dist-electron/WeChat Trade Assistant-<version>-x64.dmg
#
# 注意：要产出通用 (Universal) 包需分别构建两个架构后用 lipo 合并，
#       或用 electron-builder 的 --universal 参数（需要两套 Python 运行时）。

set -euo pipefail

# 切到项目根
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

ARCH="${ARCH:-$(uname -m)}"  # arm64 或 x86_64→映射为 x64
case "$ARCH" in
  x86_64) ARCH="x64" ;;
  arm64|aarch64) ARCH="arm64" ;;
esac

echo "=========================================="
echo " WeChat Trade Assistant - macOS 构建 ($ARCH)"
echo "=========================================="

# 1. 校验工具
echo "[1/7] 校验依赖..."
command -v python3 >/dev/null || { echo "缺少 python3"; exit 1; }
command -v node    >/dev/null || { echo "缺少 node";    exit 1; }
command -v npm     >/dev/null || { echo "缺少 npm";     exit 1; }
python3 -c "import PyInstaller" 2>/dev/null || pip install pyinstaller

# 2. 准备原生二进制资产（sqlcipher 等解密必需）
echo "[2/7] 准备原生二进制资产（sqlcipher）..."
bash installers/prepare_native_assets.sh

# 3. 安装 Python 依赖
echo "[3/7] 安装 Python 依赖..."
python3 -m pip install -r requirements.txt

# 4. PyInstaller 打包后端
echo "[4/7] PyInstaller 打包 backend..."
rm -rf dist-python build/pyi
pyinstaller installers/backend.spec --noconfirm \
  --distpath dist-python --workpath build/pyi

# 5. 安装前端依赖
echo "[5/7] 安装前端依赖..."
cd ui
[ -d node_modules ] || npm ci || npm install

# 6. 构建 Vite 前端 + 编译 Electron 主进程
echo "[6/7] 构建前端..."
npm run build

# 7. electron-builder 打包 .dmg
echo "[7/7] electron-builder 产出 .dmg..."
npx electron-builder --mac --"$ARCH"
cd ..

echo ""
echo "=========================================="
echo " 构建完成"
echo "=========================================="
echo "安装包位于：ui/dist-electron/*.dmg"
echo ""
echo "提示：首次运行时 macOS 会因未签名提示无法打开，"
echo "  右键点击应用 → 打开 → 仍要打开，或在终端执行："
echo "  sudo xattr -rd com.apple.quarantine '/Applications/WeChat Trade Assistant.app'"
echo ""
echo "如需读取微信进程内存（解密所需），首次还需对微信做 ad-hoc 重签名："
echo "  sudo codesign --force --deep --sign - /Applications/WeChat.app"
