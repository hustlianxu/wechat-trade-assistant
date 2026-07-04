#!/usr/bin/env bash
# Windows 打包脚本（在 Git Bash / WSL / MSYS2 下运行）
#
# 前置条件：
#   - Windows 10+
#   - Python 3.10+（python.exe 在 PATH）
#   - Node.js 18+ 与 npm
#   - PyInstaller: pip install pyinstaller
#   - 可选：NSIS（electron-builder 会自动调用）
#
# 用法：
#   cd <项目根>
#   bash installers/build_windows.sh
#
# 产出：
#   ui/dist-electron/WeChat Trade Assistant Setup <version>.exe

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo " WeChat Trade Assistant - Windows 构建"
echo "=========================================="

# 1. 校验工具
echo "[1/7] 校验依赖..."
command -v python >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || { echo "缺少 python"; exit 1; }
command -v node    >/dev/null || { echo "缺少 node";    exit 1; }
command -v npm     >/dev/null || { echo "缺少 npm";     exit 1; }
PYTHON_BIN="python"
command -v python >/dev/null 2>&1 || PYTHON_BIN="python3"
"$PYTHON_BIN" -c "import PyInstaller" 2>/dev/null || "$PYTHON_BIN" -m pip install pyinstaller

# 2. 准备原生二进制资产（sqlcipher 等）
echo "[2/7] 准备原生二进制资产（sqlcipher）..."
PLATFORM=windows bash installers/prepare_native_assets.sh

# 3. 安装 Python 依赖
echo "[3/7] 安装 Python 依赖..."
"$PYTHON_BIN" -m pip install -r requirements.txt

# 4. PyInstaller 打包后端
echo "[4/7] PyInstaller 打包 backend..."
rm -rf dist-python build/pyi
"$PYTHON_BIN" -m PyInstaller installers/backend.spec --noconfirm \
  --distpath dist-python --workpath build/pyi

# 5. 安装前端依赖
echo "[5/7] 安装前端依赖..."
cd ui
[ -d node_modules ] || npm ci || npm install

# 6. 构建 Vite 前端 + 编译 Electron 主进程
echo "[6/7] 构建前端..."
npm run build

# 7. electron-builder 打包 .exe
echo "[7/7] electron-builder 产出 .exe..."
npx electron-builder --win
cd ..

echo ""
echo "=========================================="
echo " 构建完成"
echo "=========================================="
echo "安装包位于：ui/dist-electron/*.exe"
echo ""
echo "提示：Windows 首次运行可能被 SmartScreen 拦截，点击『更多信息』→『仍要运行』。"
