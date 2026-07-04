# Windows 打包脚本：构建 .exe 安装包（NSIS）
#
# 前置条件：
#   - Windows 10/11
#   - Python 3.10+（建议 python.org 官方安装包，勾选 Add to PATH）
#   - Node.js 18+ 与 npm
#   - PyInstaller: pip install pyinstaller
#   - 可选：whisper.cpp 预编译二进制放入 bin\、模型放入 models\whisper\
#
# 用法（PowerShell）：
#   cd <项目根>
#   .\installers\build_windows.ps1
#
# 产出：
#   ui\dist-electron\WeChat Trade Assistant Setup <version>.exe

$ErrorActionPreference = "Stop"

# 切到项目根
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " WeChat Trade Assistant - Windows 构建" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. 校验工具
Write-Host "[1/6] 校验依赖..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command python3 -ErrorAction SilentlyContinue)) {
        throw "缺少 python，请先安装 Python 3.10+ 并加入 PATH"
    }
    Set-Alias -Name python -Value python3 -Scope Script
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "缺少 node" }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "缺少 npm" }

# 确保 PyInstaller 可用
python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "安装 PyInstaller..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

# 2. 安装 Python 依赖
Write-Host "[2/6] 安装 Python 依赖..."
python -m pip install -r requirements.txt

# 3. PyInstaller 打包后端
Write-Host "[3/6] PyInstaller 打包 backend..."
if (Test-Path "dist-python") { Remove-Item -Recurse -Force "dist-python" }
if (Test-Path "build\pyi") { Remove-Item -Recurse -Force "build\pyi" }
pyinstaller installers\backend.spec --noconfirm --distpath dist-python --workpath build\pyi
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

# 4. 安装前端依赖
Write-Host "[4/6] 安装前端依赖..."
Set-Location ui
if (-not (Test-Path "node_modules")) {
    npm ci
    if ($LASTEXITCODE -ne 0) { npm install }
}

# 5. 构建 Vite 前端 + 编译 Electron 主进程
Write-Host "[5/6] 构建前端..."
npm run build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }

# 6. electron-builder 打包 .exe (NSIS)
Write-Host "[6/6] electron-builder 产出 .exe..."
npx electron-builder --win
if ($LASTEXITCODE -ne 0) { throw "electron-builder 打包失败" }
Set-Location $ProjectRoot

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host " 构建完成" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "安装包位于：ui\dist-electron\*.exe"
Write-Host ""
Write-Host "提示：首次解密微信数据库需要以管理员身份运行应用（右键 → 以管理员身份运行）。"
