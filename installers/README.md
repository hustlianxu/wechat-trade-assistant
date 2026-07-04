# 打包与构建说明（开发者文档）

本目录包含把 WeChat Trade Assistant 打包成 macOS `.dmg` / Windows `.exe` 安装包的全部脚本与配置。

## 目录结构

```
installers/
├── backend.spec                 # PyInstaller 配置：把 Python 后端打包成可执行文件
├── build_macos.sh               # macOS 一键构建脚本（产出 .dmg）
├── build_windows.ps1            # Windows 一键构建脚本（产出 .exe）
├── prepare_native_assets.sh     # 下载 whisper.cpp 模型 / 准备原生二进制
└── README.md                    # 本文档
```

## 架构总览

应用采用 **Electron + Python** 双进程架构：

```
┌─────────────────────────────────────────────────────┐
│  WeChat Trade Assistant.app / .exe                  │
│                                                      │
│  ┌──────────────┐    spawn     ┌──────────────────┐ │
│  │  Electron    │ ───────────► │  wta-backend      │ │
│  │  (前端 UI)   │  HTTP 8765   │  (FastAPI 后端)   │ │
│  │  React+Vite  │ ◄─────────── │  PyInstaller 打包 │ │
│  └──────────────┘              └──────────────────┘ │
│         │                              │             │
│         │                              ├─ SQLite 本地库
│         │                              ├─ whisper-cli (bin/)
│         │                              └─ ggml-small.bin (models/)
│         └─ 用户交互 / 自然语言对话                       │
└─────────────────────────────────────────────────────┘
```

- **前端**：Electron 主进程 + React 渲染进程，由 `electron-builder` 打包
- **后端**：FastAPI 服务，由 `PyInstaller` 打包成 `wta-backend` 可执行文件，作为 `extraResources` 嵌入应用
- **通信**：Electron 主进程启动时 spawn 后端子进程，监听 stdout 的 `READY:<port>` 行获取端口，前端通过 `http://127.0.0.1:<port>` 调用 REST API

## 打包流程

### 1. 准备原生资源（可选但推荐）

```bash
bash installers/prepare_native_assets.sh
```

下载 whisper.cpp 模型（`ggml-small.bin`，约 466 MB）到 `models/whisper/`，并提示放置 `whisper-cli` 二进制到 `bin/`。

> whisper.cpp 无官方全平台预编译包，需各平台自行编译（脚本会打印编译命令）。未放置时后端自动降级到占位实现，不阻塞运行。

### 2. macOS 构建

```bash
bash installers/build_macos.sh            # 当前架构（arm64 或 x64）
ARCH=arm64 bash installers/build_macos.sh # 指定 Apple Silicon
ARCH=x64   bash installers/build_macos.sh # 指定 Intel
```

产出：`ui/dist-electron/WeChat Trade Assistant-<version>-<arch>.dmg`

### 3. Windows 构建

```powershell
.\installers\build_windows.ps1
```

产出：`ui\dist-electron\WeChat Trade Assistant Setup <version>.exe`

## 构建脚本做了什么

`build_macos.sh` / `build_windows.ps1` 按顺序执行 6 步：

| 步骤 | 说明 |
|------|------|
| 1. 校验依赖 | 检查 python / node / npm / PyInstaller |
| 2. 安装 Python 依赖 | `pip install -r requirements.txt` |
| 3. PyInstaller 打包后端 | 按 `backend.spec` 产出 `dist-python/wta-backend` |
| 4. 安装前端依赖 | `npm ci` 或 `npm install` |
| 5. 构建前端 | `vite build` + `tsc` 编译 Electron 主进程 |
| 6. electron-builder | 把前端 + `dist-python` + `models` + `bin` 组装成安装包 |

## PyInstaller 配置要点（`backend.spec`）

- **入口**：`src/backend/main.py`（包含 `if __name__ == "__main__": run()`）
- **hiddenimports**：用 `collect_submodules('backend')` 收集所有子模块，避免延迟导入（intent/stt 等）漏打包
- **uvicorn 子模块**：显式声明 `uvicorn.protocols.http.auto` 等，FastAPI 启动需要
- **数据文件**：`schema.sql` 必须随包
- **excludes**：排除 `torch`/`transformers`/`numpy`/`pandas` 等未启用的大依赖（whisper 走外部二进制，intent 走规则兜底），把后端体积控制在 ~80 MB

## electron-builder 资源映射（`ui/package.json`）

```json
"extraResources": [
  { "from": "../dist-python", "to": "backend-runtime" },  // PyInstaller 产出
  { "from": "../models",      "to": "models", "optional": true },
  { "from": "../bin",         "to": "bin",    "optional": true }
]
```

打包后应用内布局：

```
WeChat Trade Assistant.app/Contents/Resources/
├── backend-runtime/
│   ├── wta-backend              ← 后端可执行入口
│   ├── _internal/               ← PyInstaller 依赖
│   └── backend/                 ← backend 包源码 + schema.sql
├── models/whisper/ggml-small.bin
└── bin/whisper-cli
```

`electron/python_runner.ts` 在生产态（`app.isPackaged`）从 `process.resourcesPath` 解析上述路径并启动后端。

## 体积控制

| 组成 | 大小（估算） |
|------|------|
| Electron 框架 | ~120 MB |
| Python 后端（PyInstaller，排除 torch） | ~80 MB |
| whisper.cpp 二进制 | ~5 MB |
| ggml-small.bin 模型 | ~466 MB |
| **合计** | **~670 MB**（< 2GB 目标） |

如需进一步缩小，可改用 `ggml-tiny.bin`（~75 MB），但西语识别准确率会下降。

## 签名与分发

本项目为开源个人工具，**不做代码签名**（避免 Apple Developer 账号费用）：

- **macOS**：用户首次打开需右键 → 打开 → 仍要打开，或执行
  `sudo xattr -rd com.apple.quarantine '/Applications/WeChat Trade Assistant.app'`
- **Windows**：SmartScreen 可能提示"未知发布者"，点击"更多信息" → "仍要运行"
- **微信内存读取**（macOS SIP 限制）：需对微信做 ad-hoc 重签名，应用内设置页提供一键引导
  `sudo codesign --force --deep --sign - /Applications/WeChat.app`

## 常见构建问题

**Q: PyInstaller 报 `ModuleNotFoundError: No module named 'backend'`**
A: 确认在项目根执行，`backend.spec` 里 `pathex=['src']` 已配置。若仍失败，先 `pip install -e .` 让 backend 可被导入。

**Q: electron-builder 报 `extraResources ... not found`**
A: 先运行 `build_macos.sh`/`build_windows.ps1` 的前 3 步产出 `dist-python/`。`models`/`bin` 已设 `optional: true`，缺失不会阻断。

**Q: macOS 上 wta-backend 启动后立即退出**
A: 在终端直接运行 `WeChat Trade Assistant.app/Contents/Resources/backend-runtime/wta-backend` 查看报错。常见原因：`schema.sql` 未被打包（检查 `_internal/backend/storage/schema.sql` 是否存在）。

**Q: Windows 上后端端口被占用**
A: 默认端口 8765。可在设置页或环境变量 `WTA_PORT` 修改。
