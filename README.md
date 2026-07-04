# WeChat Trade Assistant · 南美外贸微信智能助手

一款面向南美外贸从业者的**本地优先**桌面应用，自动解析微信聊天记录（语音/文字/图片），精准识别西班牙语客户意图，自动提取待办事项，并提供**自然语言对话式查询**入口，省去手动筛选操作。

- **目标用户**：无技术背景的外贸从业者
- **运行平台**：macOS（Apple Silicon + Intel）与 Windows 10+
- **隐私安全**：所有数据处理在本地完成，绝不上传聊天记录
- **开源**：MIT 协议

## 核心功能

| 功能 | 说明 |
|------|------|
| 多版本微信自动适配 | 自动检测微信 3.6–4.0 版本，自适应密钥提取（基于 wechat-decrypt + PyWxDump 算法） |
| 聊天记录解析 | 文字直接读取；图片 .dat 解密；语音 SILK→WAV→西班牙语转录（whisper.cpp） |
| 本地数据存储 | SQLite + FTS5 全文索引，增量解析，降低微信库读取频率 |
| 客户意图识别 | Intento-v1-xlmr（本地优先）+ 规则兜底，支持 101 类意图 |
| 待办事项管理 | 自动从聊天提取（报价/发货/付款/会议…），状态跟踪 + 汇总统计 |
| 语音转录 | 打包 whisper.cpp + 西语模型，无需联网，无需用户下载 |
| **智能助手（MCP）** | **自然语言对话检索：按时间/联系人/关键词组合查询，跨语言（中西）理解，本地规则 + 可选云端 LLM** |
| 外部模型支持 | 可选配置 DeepSeek / OpenAI 兼容 API，增强意图理解与回复生成 |

## 技术栈

- **前端**：Electron 31 + React 18 + TypeScript + Vite 5
- **后端**：Python 3.10+ / FastAPI / Pydantic v2 / uvicorn
- **存储**：SQLite + FTS5（unicode61 分词，支持中文）
- **解密**：基于 [wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)，SQLCipher 4
- **STT**：[whisper.cpp](https://github.com/ggerganov/whisper.cpp)（本地，`ggml-small.bin` 多语种模型）
- **意图**：[Intento-v1-xlmr](https://huggingface.co/luigicfilho/Intento-v1-xlmr)（本地，缺省走规则兜底）
- **MCP 自然语言解析**：规则式 NER（时间/联系人/关键词/意图/动作）+ 多语言关键词扩展 + 渐进降级检索

## 目录结构

```
wechat-trade-assistant/
├── src/backend/             # Python 后端
│   ├── decrypt/             #   解密引擎（基于 wechat-decrypt）
│   ├── storage/             #   SQLite + FTS5 存储
│   ├── stt/                 #   语音转录（whisper.cpp 封装）
│   ├── intent/              #   意图识别（Intento + 规则兜底）
│   ├── todo/                #   待办提取与管理
│   ├── mcp/                 #   自然语言查询（NER + retriever + responder）
│   ├── api/                 #   FastAPI 路由与 schema
│   └── main.py              #   入口
├── ui/                      # Electron + React 前端
│   ├── electron/            #   主进程 / preload / Python 启动器
│   └── src/                 #   页面（仪表盘/聊天/意图/待办/助手/设置）
├── models/                  # whisper / intent 模型文件（打包时嵌入）
├── installers/              # 打包脚本与配置（详见 installers/README.md）
├── tests/                   # pytest 测试用例 + mock 数据
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 开发环境

### 后端

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .                                     # 让 backend 包可被导入

# 启动后端（默认 127.0.0.1:8765）
WTA_PORT=8765 python -m backend.main
# 浏览器打开 http://127.0.0.1:8765/docs 查看 API 文档
```

### 前端

```bash
cd ui
npm install
npm run dev    # 启动 Vite dev server + Electron（开发态自动连接后端）
```

### 运行测试

```bash
# 在项目根执行
python -m pytest -q
```

测试覆盖：解密适配、SQLite/FTS 存储、规则意图识别、待办提取、NER 时间/联系人/关键词解析、MCP 端到端三场景（总结/对比/列待办）、FastAPI 路由。

## 打包安装包

详见 [installers/README.md](installers/README.md)。简要：

```bash
# 1. 准备 whisper.cpp 模型（可选）
bash installers/prepare_native_assets.sh

# 2. macOS .dmg
bash installers/build_macos.sh

# 3. Windows .exe（PowerShell）
.\installers\build_windows.ps1
```

产出位于 `ui/dist-electron/`。

## 隐私与安全

- **所有数据本地存储**：聊天记录、转录文本、意图标签均落在用户本机 SQLite，不上传任何原始数据
- **本地推理优先**：语音转录（whisper.cpp）、意图识别（规则/Intento）均在本地完成
- **云端可选**：仅在用户主动配置 API Key 后，才会把**检索后的结构化片段**发送给 LLM 生成自然语言回复，原始聊天记录永不外发
- **数据库可选加密**：支持 SQLCipher 加密本地库（需安装 pysqlcipher3）

## 致谢

本项目站在以下开源项目的肩膀上：

- [wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) — 微信 4.0 / 企业微信 5.x 数据库解密
- [PyWxDump](https://github.com/xaoyaoo/PyWxDump) — 多版本微信自适应密钥提取算法
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — 本地语音转文字
- [Intento-v1-xlmr](https://huggingface.co/luigicfilho/Intento-v1-xlmr) — 多语言意图分类

## 许可证

MIT
