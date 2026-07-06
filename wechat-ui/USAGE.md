# WeChat UI 使用手册

仿微信 PC 端的 Web 界面，基于 [wechat-decrypt](https://github.com/xMduo/wechat-decrypt) 解密后的数据库，提供联系人/群聊浏览、消息查看、语音转录（西班牙语/英语/普通话）、会话级意图识别与待办事项提取等外贸场景能力。

> 本项目只读取 wechat-decrypt **解密后**的明文 SQLite 文件，不涉及密钥提取与解密流程。请先用 wechat-decrypt 完成解密，再用本项目浏览分析。

---

## 目录

- [一、功能特性](#一功能特性)
- [二、系统架构](#二系统架构)
- [三、环境要求](#三环境要求)
- [四、快速开始](#四快速开始)
- [五、配置详解](#五配置详解)
- [六、语音转录](#六语音转录)
- [七、多 LLM 配置](#七多-llm-配置)
- [八、意图识别 / 待办 / 总结](#八意图识别--待办--总结)
- [九、API 文档](#九api-文档)
- [十、测试](#十测试)
- [十一、数据库结构说明](#十一数据库结构说明)
- [十二、常见问题](#十二常见问题)
- [十三、变更日志（2026-07-07）](#十三变更日志2026-07-07)

---

## 一、功能特性

### 1. 仿微信 PC 端三栏布局

| 区域 | 宽度 | 功能 |
|------|------|------|
| 左栏 | 300px | 联系人列表，3 个 Tab：**好友 / 群聊 / 最近** |
| 中栏 | 自适应 | 聊天记录区，按微信逻辑渲染各类消息 |
| 右栏 | 320px | 时间筛选 + 意图识别 + 待办提取 + 会话总结 |

### 2. 列表排序逻辑（与微信一致）

- **好友**：按备注名（无备注则用昵称）字母顺序排序
- **群聊**：按各群聊最近一次聊天记录的时间**倒序**排列
- **最近**：与群聊逻辑一致，按最近一次聊天时间**倒序**排列

### 3. 消息显示规则

- **本人发出的消息**：靠聊天窗口**右侧**，绿色气泡（`#95ec69`）
- **对方发出的消息**：靠**左侧**，白色气泡
- 群聊中显示发送者昵称
- 5 分钟间隔自动显示时间分隔线
- 支持的消息类型：文本、图片、语音、视频、链接/文件、位置、表情、系统消息、撤回

### 4. 语音转录（外贸场景）

- 主要支持 **西班牙语**、**少量英语**、**普通话**
- 本地优先：whisper.cpp 离线转录（推荐，精准且免费）
- LLM 兜底：本地不可用时调用配置的 LLM Whisper API
- 转录结果在气泡中显示，并标注来源（`whisper_cpp` / `llm`）

### 5. 多 LLM 配置

- 支持同时配置多个 LLM Provider（OpenAI / DeepSeek / Moonshot / Claude / 本地 Ollama 等）
- 通过 `active_llm` 名称**自定义激活**当前使用的 LLM
- 所有 LLM 走 OpenAI 兼容接口，配置统一

### 6. 会话级智能分析

- **意图识别**：12 类外贸意图分类（问候、询盘、报价、下单、付款、物流等）
- **待办事项提取**：从会话中抽取待办任务及截止时间
- **会话总结**：生成本次会话的核心内容摘要
- 无 LLM 时意图识别走中西英三语关键词规则兜底

---

## 二、系统架构

```
┌──────────────────────────────────────────────────────────┐
│  浏览器（React 18 + Vite + TypeScript）                  │
│  ┌────────────┬─────────────────────┬─────────────────┐  │
│  │ ContactList │     ChatView        │   SidePanel     │  │
│  │ 好友/群/最近 │  消息气泡 + 语音    │ 时间/意图/待办  │  │
│  └────────────┴─────────────────────┴─────────────────┘  │
│         │ fetch /api/* (Vite proxy → 8766)               │
└─────────┼────────────────────────────────────────────────┘
          ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI 后端（端口 8766）                               │
│  ┌──────────┬───────────┬──────────┬──────────────────┐  │
│  │ config   │ db_reader │  voice   │       llm        │  │
│  │ 配置管理 │ 数据库读取│ SILK→WAV │ 意图/待办/总结    │  │
│  └──────────┴───────────┴──────────┴──────────────────┘  │
│         │                         │                      │
│         ▼                         ▼                      │
│  ┌──────────────────┐    ┌──────────────────┐            │
│  │ wechat-decrypt   │    │ whisper.cpp /    │            │
│  │ 解密后的 SQLite  │    │ LLM Whisper API  │            │
│  │ decrypted/       │    │                  │            │
│  └──────────────────┘    └──────────────────┘            │
└──────────────────────────────────────────────────────────┘
```

**技术栈**：

- 前端：React 18 + Vite 5 + TypeScript 5（无 UI 框架，纯 CSS 仿微信）
- 后端：Python 3.10+ / FastAPI / Pydantic 2
- 数据：直接读取 wechat-decrypt 解密后的 SQLite 文件（无需导入）
- 语音：whisper.cpp（本地优先）+ OpenAI Whisper 兼容 API（兜底）
- LLM：OpenAI 兼容 chat/completions 接口

---

## 三、环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | 后端运行时（推荐 3.11 / 3.12） |
| Node.js | ≥ 18 | 前端构建（推荐 20 LTS） |
| npm | ≥ 9 | 随 Node 安装 |
| wechat-decrypt | 任意版本 | 已完成解密，产出 `decrypted/` 目录 |

**可选依赖**（按需启用）：

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| whisper.cpp | 本地语音转录 | `brew install whisper-cpp`（macOS）或 [源码编译](https://github.com/ggerganov/whisper.cpp) |
| ffmpeg | SILK → WAV 兜底 | `brew install ffmpeg` / `apt install ffmpeg` |
| silk_v3_decoder | SILK → WAV 备选 | [github.com/kn007/silk-v3-decoder](https://github.com/kn007/silk-v3-decoder) |
| pysilk-mod | SILK → WAV Python 库 | `pip install pysilk-mod` |

---

## 四、快速开始

本项目**全自动检测配置**，无需手动填写路径。前提是已用 wechat-decrypt 完成至少一次解密（产出 `decrypted/` 目录或 `all_keys.json`）。

### 步骤 1：（一次性）安装 wechat-decrypt 并完成首次解密

如果还没有解密过微信数据，需要先按 wechat-decrypt 项目说明完成首次解密。**macOS 上首次解密需要以下步骤**（之后增量解密会自动完成）：

```bash
# 1. 克隆 wechat-decrypt
git clone https://github.com/xMduo/wechat-decrypt.git
cd wechat-decrypt
pip install -r requirements.txt

# 2. 退出微信并重签名（一次性，仅 macOS 需要）
killall WeChat
sudo codesign --force --deep --sign - /Applications/WeChat.app

# 3. 启动微信并登录

# 4. 编译并运行密钥提取器（仅 macOS 需要，Windows 用 python find_all_keys.py）
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation
sudo ./find_all_keys_macos
# 产出 all_keys.json

# 5. 解密所有数据库（产出 decrypted/ 目录）
python decrypt_db.py
```

> 完成后，`all_keys.json` 和 `decrypted/` 会保留下来，**之后本项目会自动增量解密**，无需重复上述步骤。

### 步骤 2：安装本项目依赖

```bash
cd wechat-ui
pip install -r backend/requirements.txt

cd frontend
npm install
```

### 步骤 3：启动后端（自动检测配置）

```bash
cd wechat-ui
python -m backend.main
```

**后端启动时会自动执行**：
1. 检查 `~/.wta_ui/config.json` 配置是否完整
2. 若不完整，自动扫描以下位置找已解密目录：
   - wechat-decrypt 的 `config.json` 中的 `decrypted_dir`
   - wechat-decrypt 项目目录下的 `decrypted/`
   - wechat-ui 同级目录、`~/.wta_ui/decrypted/`、`/tmp/wechat_decrypted/`
3. 若找不到已解密目录但 `all_keys.json` 存在，**自动调用 `decrypt_db.py -i` 增量解密**
4. 自动检测微信数据目录（macOS/Windows/Linux 标准路径）
5. 自动推断本人 wxid（从数据目录名或消息表统计）
6. 自动检测 whisper.cpp（PATH / Homebrew / 项目本地）
7. 自动写回 `~/.wta_ui/config.json`

启动日志会打印检测过程，例如：
```
[startup] 配置不完整，开始自动检测...
[startup] 自动配置完成：['decrypted_dir', 'wechat_base_dir', 'self_wxid']
[startup]   ✓ 检测到已解密目录：/path/to/decrypted
[startup]   ✓ 检测到微信数据目录：/path/to/xwechat_files/wxid_xxx
[startup]   ✓ 检测到本人 wxid：wxid_xxx
```

### 步骤 4：启动前端

```bash
cd wechat-ui/frontend
npm run dev
```

启动后访问 [http://localhost:5173](http://localhost:5173)，应直接看到联系人列表。

> Vite 开发服务器已配置代理：`/api/*` → `http://localhost:8766`，无需处理跨域。

### 步骤 5：（可选）手动触发自动检测

如果自动检测未成功，或想重新检测：

1. 前端左上角点击「设置」
2. 在「数据目录」分组右上角点击 **「🔍 自动检测」** 按钮
3. 查看检测结果卡片，会列出每一步的检测信息
4. 若提示需要手动操作（如 macOS 需先运行密钥提取器），按提示完成即可

也可以通过 API 手动触发：

```bash
# 查询当前检测状态
curl http://localhost:8766/api/auto-setup/status

# 强制重新检测并写回配置
curl -X POST "http://localhost:8766/api/auto-setup?force=true"
```

### 步骤 6：（可选）构建生产版本

```bash
cd wechat-ui/frontend
npm run build      # 产物输出到 wechat-ui/frontend/dist/
npm run preview    # 本地预览构建产物
```

构建后可用任意静态服务器托管 `dist/`，只需把 `/api` 反代到 8766 即可。

### 自动检测的覆盖范围

| 检测项 | 检测来源 | 是否需要手动 |
|--------|----------|-------------|
| wechat-decrypt 项目目录 | 环境变量 `WECHAT_DECRYPT_DIR` / 同级目录 / `~/wechat-decrypt` | 否 |
| 已解密目录 `decrypted/` | wechat-decrypt config / 项目目录 / 常见路径 | 否 |
| 自动增量解密 | 调用 `decrypt_db.py -i`（需 `all_keys.json` 存在） | 仅首次需手动提取密钥 |
| 微信数据目录 | wechat-decrypt `auto_detect_db_dir` + 标准路径扫描 | 否 |
| 本人 wxid | 数据目录名 / 消息表发送频次统计 | 否 |
| whisper.cpp | PATH / Homebrew / 项目本地 bin | 否（可选依赖） |
| LLM 配置 | 需用户在设置页填写 API Key | 是（仅 LLM 功能必需） |

> **只有 LLM API Key 需要用户手动填写**，其余全部自动。如果只浏览消息和本地语音转录，连 LLM 也不需要。

---

## 五、配置详解

配置文件位于 `~/.wta_ui/config.json`，首次运行自动创建。也可通过前端「设置」页修改。

### 完整配置示例

```json
{
  "decrypted_dir": "/Users/you/wechat-decrypt/decrypted",
  "wechat_base_dir": "/Users/you/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files",
  "self_wxid": "wxid_abcdef1234567",
  "whisper": {
    "binary_path": "/opt/homebrew/bin/whisper-cpp",
    "model_path": "/opt/homebrew/share/whisper-cpp/ggml-large-v3.bin",
    "language": "es"
  },
  "llm_providers": [
    {
      "name": "deepseek",
      "api_base": "https://api.deepseek.com/v1",
      "api_key": "sk-xxxxxxxx",
      "model": "deepseek-chat",
      "temperature": 0.3,
      "max_tokens": 2000
    },
    {
      "name": "openai",
      "api_base": "https://api.openai.com/v1",
      "api_key": "sk-xxxxxxxx",
      "model": "gpt-4o-mini",
      "whisper_model": "whisper-1"
    },
    {
      "name": "ollama-local",
      "api_base": "http://localhost:11434/v1",
      "api_key": "ollama",
      "model": "qwen2.5:7b"
    }
  ],
  "active_llm": "deepseek"
}
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `decrypted_dir` | wechat-decrypt 解密后的目录绝对路径 |
| `wechat_base_dir` | 微信数据根目录（用于定位语音/图片原始文件，可留空） |
| `self_wxid` | 本账号 wxid，用于区分本人/对方消息，过滤联系人列表中的自己 |
| `whisper.binary_path` | whisper.cpp 可执行文件路径 |
| `whisper.model_path` | whisper.cpp 模型文件路径 |
| `whisper.language` | 语言提示：`es`=西语、`en`=英语、`zh`=普通话、空=自动检测 |
| `llm_providers` | LLM Provider 列表，可配多个 |
| `llm_providers[].name` | 唯一名称，用于 `active_llm` 引用 |
| `llm_providers[].api_base` | OpenAI 兼容 API 地址（注意带 `/v1`） |
| `llm_providers[].api_key` | API Key（本地 Ollama 可填任意值） |
| `llm_providers[].model` | chat 模型名 |
| `llm_providers[].whisper_model` | （可选）语音转录模型名，如 `whisper-1`，留空则该 LLM 不参与语音兜底 |
| `active_llm` | 当前激活的 LLM 名称，必须与某个 provider 的 `name` 一致 |

---

## 六、语音转录

### 转录流程

```
SILK 数据 (media_*.db VoiceInfo.voice_data)
    │
    │ 1. 剥离首字节 0x02（SILK 头）
    ▼
SILK 纯净数据
    │
    │ 2. SILK → WAV（三选一）
    │    ├─ pysilk-mod（pip 安装，优先）
    │    ├─ silk_v3_decoder（命令行）
    │    └─ ffmpeg（兜底）
    ▼
WAV 音频
    │
    │ 3. 转录
    │    ├─ whisper.cpp 本地（优先）
    │    └─ LLM Whisper API（兜底）
    ▼
转录文本 + 来源标签
```

### whisper.cpp 安装

#### macOS（推荐）

```bash
brew install whisper-cpp
# 模型默认装在 /opt/homebrew/share/whisper-cpp/
# 下载大模型（更精准，约 3GB）：
brew install whisper-cpp --HEAD
# 或手动下载 ggml-large-v3.bin 到 /opt/homebrew/share/whisper-cpp/
```

#### Linux / 源码编译

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
make
# 下载模型
./models/download-ggml-model.sh large-v3
# 二进制：./build/bin/whisper-cli
# 模型：./models/ggml-large-v3.bin
```

### 模型选择建议

| 模型 | 大小 | 西语精准度 | 速度 | 推荐场景 |
|------|------|-----------|------|----------|
| `ggml-base.bin` | 142MB | 一般 | 快 | 快速预览 |
| `ggml-medium.bin` | 1.5GB | 较好 | 中 | 日常使用 |
| `ggml-large-v3.bin` | 3GB | 优秀 | 慢 | 外贸精准转录 |

> 西班牙语转录推荐 `medium` 及以上，配合 `language: "es"` 提示可显著提升准确率。

### 在前端使用

1. 打开会话，找到语音消息气泡
2. 点击「转录」按钮
3. 等待几秒，转录文本显示在气泡内，并标注来源（`whisper_cpp` / `llm`）
4. 点击「播放」按钮可直接播放原始语音

---

## 七、多 LLM 配置

### 支持的 Provider

本项目支持任何**兼容 OpenAI chat/completions 接口**的 LLM：

| Provider | api_base | 备注 |
|----------|----------|------|
| OpenAI | `https://api.openai.com/v1` | 官方，支持 Whisper |
| DeepSeek | `https://api.deepseek.com/v1` | 国内可直连，性价比高 |
| Moonshot (Kimi) | `https://api.moonshot.cn/v1` | 国内可用 |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 阿里云 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | 智谱 |
| Ollama (本地) | `http://localhost:11434/v1` | 完全离线，api_key 任意 |
| vLLM / LM Studio | `http://localhost:8000/v1` | 本地部署 |

### 配置示例（多 Provider + 单选激活）

```json
{
  "llm_providers": [
    {
      "name": "deepseek",
      "api_base": "https://api.deepseek.com/v1",
      "api_key": "sk-xxx",
      "model": "deepseek-chat",
      "temperature": 0.3
    },
    {
      "name": "ollama",
      "api_base": "http://localhost:11434/v1",
      "api_key": "ollama",
      "model": "qwen2.5:7b"
    }
  ],
  "active_llm": "deepseek"
}
```

### 切换激活的 LLM

- **前端**：设置页 → LLM 列表中点选「激活」单选按钮
- **配置文件**：修改 `active_llm` 字段为对应 provider 的 `name`
- 切换后立即生效，无需重启后端

### 测试 LLM 连通性（新增）

每个 Provider 卡片右侧有「测试连通性」按钮，**无需先保存配置**即可验证：

1. 填好 `name` / `model` / `api_base` / `api_key`
2. 点「测试连通性」
3. 查看结果卡片：
   - **成功**：显示绿色「✓ 连通成功」+ provider 主机名 + LLM 响应预览
   - **失败**：显示红色「✗ 连通失败」+ 配置提示（如「api_base 可能缺少 /v1 后缀」）+ 详细错误（如 HTTP 401 未授权）

> 后端会自动清理 `api_base` 中混入的反引号/引号/空格（从 Markdown 文档复制时常见），并对已知 provider（DeepSeek / OpenAI / Moonshot 等）检测 `/v1` 后缀缺失。

### 语音转录专用 LLM

如需用 LLM 兜底转录语音，给 provider 添加 `whisper_model` 字段：

```json
{
  "name": "openai",
  "api_base": "https://api.openai.com/v1",
  "api_key": "sk-xxx",
  "model": "gpt-4o-mini",
  "whisper_model": "whisper-1"
}
```

转录时优先级：whisper.cpp 本地 → 激活 LLM 的 Whisper API。

---

## 八、意图识别 / 待办 / 总结

均针对**当前选中的会话**，可结合右栏的时间范围筛选。

### 1. 意图识别

识别 12 类外贸意图：

| 意图 | 说明 |
|------|------|
| `greeting` | 问候 / 打招呼 |
| `inquiry` | 询盘 / 产品咨询 |
| `quote` | 报价 / 价格相关 |
| `order` | 下单 / 订单相关 |
| `payment` | 付款 / 汇款相关 |
| `shipping` | 物流 / 发货相关 |
| `complaint` | 投诉 / 售后 |
| `sample` | 样品相关 |
| `spec` | 规格 / 参数咨询 |
| `visit` | 来访 / 验厂 |
| `farewell` | 告别 |
| `other` | 其他 |

- 配置了 LLM 时走 LLM 分析
- 未配置 LLM 时走**中西英三语关键词规则兜底**（精度有限但可用）

### 2. 待办事项提取

从会话中抽取待办任务，返回结构化结果：

```json
{
  "todos": [
    {
      "title": "周五前发送报价单",
      "due": "2026-07-10",
      "assignee": "自己",
      "priority": "high"
    }
  ]
}
```

> 待办提取需配置 LLM，无 LLM 时返回空列表。

### 3. 会话总结

生成本次会话的核心摘要，包含主要议题、关键结论、下一步行动。

> 会话总结需配置 LLM，无 LLM 时返回提示信息。

### 在右栏使用

1. 选中左侧某个会话
2. 在右栏用时间选择器圈定范围（可选，默认全部）
3. 点击「意图识别」「提取待办」「会话总结」按钮
4. 结果显示在按钮下方的卡片中

---

## 九、API 文档

后端默认监听 `http://localhost:8766`，所有接口以 `/api` 为前缀。

### 健康检查

```
GET /api/health
```

返回当前配置状态（不泄露密钥）。

### 配置

```
GET /api/config          # 读取配置
POST /api/config         # 更新配置（部分字段，body 为 JSON）
```

### 自动检测与自动解密

```
GET  /api/auto-setup/status        # 查询检测状态（不修改配置）
POST /api/auto-setup?force=false   # 触发自动检测并写回配置
```

`POST /api/auto-setup` 返回：

```json
{
  "decrypted_dir": "/path/to/decrypted",
  "wechat_base_dir": "/path/to/xwechat_files/wxid_xxx",
  "self_wxid": "wxid_xxx",
  "whisper": {"binary_path": "...", "model_path": "...", "language": ""},
  "auto_setup_status": "ok",          // ok | partial | failed
  "messages": ["✓ 检测到已解密目录：...", ...],
  "needs_manual_action": null          // 非空时为需要手动操作的提示
}
```

### 增量解密（新增）

```
POST /api/decrypt/incremental      # 只拉取本地库中最新消息之后的新消息
```

复用 wechat-decrypt 的 `decrypt_db.py -i` 增量模式，**不重新解密联系人库**，速度快。
完成后自动把新的 `decrypted_dir` 写回配置并重置 reader 缓存。

返回：

```json
{
  "ok": true,
  "decrypted_dir": "/path/to/decrypted",
  "decrypted_count": 5,
  "message": "解密成功（增量模式，5 个数据库）"
}
```

> 失败时 `ok=false`，`message` 携带原因（如「未找到 wechat-decrypt 项目目录」「未找到密钥文件 all_keys.json」）。

### LLM 连通性测试（新增）

```
POST /api/llm/test                 # 测试某个 provider 的连通性（无需先保存）
```

请求 body 即一个完整的 provider 配置：

```json
{
  "name": "deepseek",
  "api_base": "https://api.deepseek.com/v1",
  "api_key": "sk-xxx",
  "model": "deepseek-chat",
  "temperature": 0.3,
  "max_tokens": 2000
}
```

返回：

```json
{
  "ok": true,
  "provider": "api.deepseek.com",
  "model": "deepseek-chat",
  "api_base": "https://api.deepseek.com/v1",
  "response": "ok",
  "error": "",
  "config_hint": ""
}
```

> 失败时 `ok=false`：`config_hint` 携带配置问题（如缺 `/v1`），`error` 携带调用诊断（如 HTTP 401/404/5xx）。

### 联系人

```
GET /api/contacts?type=friends&sort=name      # 好友（按名排序）
GET /api/contacts?type=groups                 # 群聊（按时间倒序）
GET /api/contacts?type=recent                 # 最近（按时间倒序）
GET /api/contacts/{username}                  # 单个联系人详情
```

### 消息

```
GET /api/messages/{username}?start_ts=0&end_ts=0&limit=500&offset=0
GET /api/search?keyword=价格&username=&limit=100
```

### 语音

```
GET  /api/voice/{username}/{local_id}         # WAV 音频流（可直接 <audio> 播放）
POST /api/transcribe                           # 转录语音，body: {username, local_id}
```

`transcribe` 返回 `{"text": "...", "source": "whisper_cpp|llm|error"}`。

### 智能分析

```
POST /api/analyze/intent/{username}?start_ts=&end_ts=&limit=100
POST /api/analyze/todos/{username}?start_ts=&end_ts=&limit=100
POST /api/analyze/summary/{username}?start_ts=&end_ts=&limit=200
```

时间戳均为秒级 Unix 时间戳，`0` 表示不限。

> 三个接口的返回都新增了 `llm_error` 字段：LLM 调用失败时携带诊断信息（如「HTTP 401 未授权」「api_base 可能缺少 /v1 后缀」），前端会直接展示，不再静默吞掉错误。

---

## 十、测试

### 运行后端单元测试

测试使用模拟的 SQLite 数据库，不依赖真实微信数据。

```bash
cd wechat-ui
pip install -r backend/requirements.txt   # 已含 pytest / httpx
python -m pytest tests/ -v
```

预期输出：

```
========================= 66 passed in 1s =========================
```

测试覆盖：

| 模块 | 测试数 | 覆盖点 |
|------|--------|--------|
| `TestMsgType` | 3 | 复合类型拆分、类型名映射 |
| `TestDbReader` | 12 | 初始化、好友/群/最近列表、消息列表、时间过滤、分页、语音数据、搜索、群消息前缀剥离 |
| `TestConfig` | 2 | 默认配置、保存加载 |
| `TestLLM` | 6 | 客户端可用性、规则意图识别（中西英）、激活 LLM 切换 |
| `TestAPI` | 12 | 全部 API 端点（含 `/api/auto-setup`、`/api/auto-setup/status`） |
| `TestAutoSetup` | 10 | 解密目录校验、wxid 格式判断、本人 wxid 推断、whisper 检测、解密输出解析、run_auto_setup 全流程、**开发目录扫描（~/Study/ 等）** |
| `TestLLMErrorHandling` | 16 | **api_base 反引号/空格清理、/v1 后缀检测、HTTP 错误诊断（401/404/500）、chat 返回 (content, error) 元组、classify_intent 透传 llm_error** |
| `TestAPIExtra` | 5 | **`/api/llm/test` 配置校验与反引号清理、`/api/decrypt/incremental` 成功与失败路径** |

### 前端类型检查与构建

```bash
cd wechat-ui/frontend
npx tsc --noEmit      # 类型检查，应 0 错误
npm run build         # 生产构建，输出到 dist/
```

预期构建产物：

```
dist/index.html                   0.40 kB │ gzip:  0.31 kB
dist/assets/index-Drckpal9.css   17.46 kB │ gzip:  3.59 kB
dist/assets/index-C1Vwj759.js   169.04 kB │ gzip: 53.79 kB
```

### 后端联调烟雾测试

```bash
cd wechat-ui
python -m backend.main &
sleep 2
curl http://localhost:8766/api/health
curl http://localhost:8766/api/config
```

---

## 十一、数据库结构说明

本项目直接读取 wechat-decrypt 解密后的 SQLite 文件，核心表结构：

### contact.db → `contact` 表

| 字段 | 说明 |
|------|------|
| `username` | wxid 或 `xxx@chatroom`（群聊） |
| `nick_name` | 昵称 |
| `remark` | 备注名 |
| `alias` | 微信号 |
| `local_type` | 联系人类型（1=好友, 2=群, 3=群成员应过滤） |

### session.db → `SessionTable`

| 字段 | 说明 |
|------|------|
| `username` | 会话对方 wxid |
| `summary` | 最后一条消息摘要（可能 zstd 压缩） |
| `last_timestamp` | 最后消息时间戳 |
| `unread_count` | 未读数 |

### message_N.db

- `Name2Id`：`rowid` ↔ `user_name` 映射
- `Msg_<md5(username)>`：每个会话一张表，字段含 `local_id, server_id, local_type, create_time, real_sender_id, message_content, WCDB_CT_message_content`
  - `WCDB_CT_message_content=4` 表示 message_content 是 zstd 压缩
  - 群消息 `message_content` 形如 `wxid_xxx:\n<内容>`，本项目自动剥离前缀

### media_N.db → `VoiceInfo`

| 字段 | 说明 |
|------|------|
| `chat_name_id` | 关联 `Name2Id.rowid` |
| `local_id` | 关联消息 local_id |
| `voice_data` | SILK 音频 BLOB（首字节 `0x02` 为 SILK 头，需剥离） |

### 消息类型编码

`local_type` 是复合编码 `(sub_type << 32) | base_type`，取低 32 位为基础类型：

| base_type | 类型 |
|-----------|------|
| 1 | 文本 |
| 3 | 图片 |
| 34 | 语音 |
| 43 | 视频 |
| 49 | 链接 / 文件 / 小程序 |
| 10000 | 系统消息 |
| 10002 | 撤回 |

---

## 十二、常见问题

### Q1：左侧列表为空 / 报错「解密目录不存在」？

本项目**全自动检测**，正常情况无需手动配置。若报错：

1. **先点「设置 → 🔍 自动检测」按钮**，让程序重新扫描
2. 查看检测结果卡片，若提示「未找到已解密目录」，说明还没用 wechat-decrypt 解密过
3. 按「快速开始 → 步骤 1」完成首次解密（产出 `decrypted/` 或 `all_keys.json`）
4. 若提示「未找到密钥文件 all_keys.json」且在 macOS，需先运行密钥提取器：
   ```bash
   killall WeChat
   sudo codesign --force --deep --sign - /Applications/WeChat.app
   # 启动微信登录
   cd <wechat-decrypt 目录>
   cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation
   sudo ./find_all_keys_macos
   ```
5. 完成后回来重试自动检测，程序会自动调 `decrypt_db.py -i` 增量解密

**已解密但检测不到？** 程序现在会扫描以下位置查找 `decrypted/` 目录：
- wechat-decrypt 的 `config.json` 中 `decrypted_dir`
- wechat-decrypt 项目目录、wechat-ui 同级目录
- **开发目录**：`~/Study/`、`~/Projects/`、`~/code/`、`~/workspace/` 等下的 `wechat-decrypt/decrypted`（用户常把项目克隆在这里）
- `~/.wta_ui/decrypted/`、`/tmp/wechat_decrypted/`

也可通过环境变量指定 wechat-decrypt 位置：`export WECHAT_DECRYPT_DIR=/path/to/wechat-decrypt`

**只想拉取最新消息？** 点「设置 → ⬆ 增量同步」按钮，只解密本地库中最新消息之后的新消息，不重新解密联系人库，速度快。

### Q2：消息不显示 / 显示不全？

- `self_wxid` 由程序自动从数据目录名或消息表发送频次推断，若不准可在设置页手动改
- 消息可能分散在多个 `message_N.db` 分片，本项目会自动遍历
- 3.x 版微信文件名大写，本项目已自动兼容大小写

### Q3：语音转录失败？

按顺序排查：

1. **SILK → WAV 失败**：安装 `pysilk-mod` 或 `ffmpeg` 或 `silk_v3_decoder` 之一
2. **whisper.cpp 不可用**：检查 `binary_path` 和 `model_path` 是否存在
3. **LLM 兜底失败**：给激活的 LLM 配置 `whisper_model` 字段

错误信息会显示在转录结果中，如 `[语音转录失败：...]`。

### Q4：意图识别 / 待办 / 总结不工作？

- 这些功能**需要配置 LLM**（待办和总结必须有 LLM，意图识别无 LLM 时走规则兜底）
- 确认 `active_llm` 指向的 provider 名称存在且 `api_key` 有效
- 在 `/api/health` 返回中 `llm_configured` 应为 `true`
- **先点「测试连通性」按钮**验证配置：会自动检测 `api_base` 是否缺少 `/v1` 后缀、`api_key` 是否有效（HTTP 401）、`model` 是否存在（HTTP 404/400）
- 分析失败时右栏会直接显示 `llm_error` 诊断信息（不再静默吞掉错误）

### Q5：如何切换 LLM？

- 前端：设置页 → LLM 列表 → 点选「激活」
- 配置文件：修改 `active_llm` 字段
- 切换立即生效，无需重启

### Q6：群聊消息不显示发送者？

- 群消息发送者通过 `real_sender_id` → `Name2Id` 映射获取
- 若 `Name2Id` 表缺失该 rowid，发送者显示为空
- 这是 wechat-decrypt 解密后的数据特性，非本项目 bug

### Q7：可以同时浏览多个微信账号吗？

- 当前设计为单账号：一个 `decrypted_dir` + 一个 `self_wxid`
- 多账号需切换配置后刷新（设置页修改 `decrypted_dir` 即自动重建 reader 缓存）

### Q8：数据会被修改吗？

- **不会**。本项目只读打开所有 SQLite 文件（`sqlite3.connect` 默认只读访问明文 db）
- 不会写入任何微信数据库
- 配置仅写入 `~/.wta_ui/config.json`

### Q9：如何部署到服务器供团队访问？

```bash
# 后端
cd wechat-ui
nohup uvicorn backend.main:app --host 0.0.0.0 --port 8766 &

# 前端构建 + nginx 托管
cd frontend && npm run build
# 将 dist/ 部署到 nginx，并把 /api 反代到 8766
```

nginx 示例：

```nginx
server {
    listen 80;
    server_name your.domain.com;
    root /path/to/wechat-ui/frontend/dist;
    location / { try_files $uri /index.html; }
    location /api/ { proxy_pass http://127.0.0.1:8766; }
}
```

> 注意：微信聊天数据涉及隐私，部署到公网请务必加访问控制。

---

## 项目结构

```
wechat-ui/
├── backend/
│   ├── config.py          # 配置管理（~/.wta_ui/config.json）
│   ├── auto_setup.py      # 自动检测微信目录、自动解密、自动推断 wxid/whisper
│   ├── db_reader.py       # 解密数据库读取器（核心）
│   ├── voice.py           # SILK → WAV → whisper.cpp / LLM 转录
│   ├── llm.py             # 多 LLM、意图识别、待办、总结
│   ├── main.py            # FastAPI 应用（端口 8766，启动时自动 setup）
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/client.ts          # API 封装
│   │   ├── types/index.ts         # TypeScript 类型
│   │   ├── components/
│   │   │   ├── ContactList.tsx    # 左栏：3 Tab + 搜索
│   │   │   ├── ChatView.tsx       # 中栏：消息列表
│   │   │   ├── MessageBubble.tsx  # 消息气泡（各类渲染）
│   │   │   ├── VoiceMessage.tsx   # 语音消息（播放+转录）
│   │   │   ├── SidePanel.tsx      # 右栏：时间+分析
│   │   │   └── Settings.tsx       # 设置弹窗
│   │   ├── utils/format.ts        # 时间/格式化
│   │   ├── styles/global.css      # 仿微信样式
│   │   ├── App.tsx                # 三栏布局
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts     # 端口 5173，/api 代理 8766
├── tests/
│   └── test_backend.py    # 66 个单元测试（含 auto_setup / LLM 错误处理 / 增量解密端点）
└── pyproject.toml         # pytest 配置
```

---

## 十三、变更日志（2026-07-07）

本次更新修复了昨天到现在提出的三个问题。所有变更均已通过测试（66 个测试通过、tsc 0 错误、vite build 成功）。

### 修复 1：LLM 报错无日志 → 错误透传 + 配置校验

**问题**：LLM 调用失败时（如 api_key 无效、api_base 缺 `/v1`、model 名错），原代码静默返回 `None`，前端只看到「分析失败」，无法定位原因。

**改动文件**：
- [backend/llm.py](backend/llm.py)
- [backend/main.py](backend/main.py)
- [frontend/src/components/Settings.tsx](frontend/src/components/Settings.tsx)
- [frontend/src/api/client.ts](frontend/src/api/client.ts)
- [frontend/src/types/index.ts](frontend/src/types/index.ts)

**具体变更**：
1. `LLMClient.chat()` 返回类型从 `Optional[str]` 改为 `tuple[Optional[str], str]`（content, error）
2. 新增 `_sanitize_api_base()`：自动清理 `api_base` 中混入的反引号/单双引号/空格/末尾斜杠（从 Markdown 文档复制时常见）
3. 新增 `validate_api_base()`：对已知 provider（DeepSeek / OpenAI / Moonshot / 通义 / 智谱 / SiliconFlow）检测 `/v1` 后缀缺失
4. 新增 `_diagnose_http_error()`：针对 401/404/400/5xx 构造可读诊断信息
5. `classify_intent` / `extract_todos` / `summarize_conversation` 全部透传 `llm_error` 字段
6. 三个分析端点（`/api/analyze/intent|todos|summary`）返回值新增 `llm_error` 字段
7. 新增 `POST /api/llm/test` 端点：测试 provider 连通性，返回 `ok` / `provider` / `response` / `error` / `config_hint`
8. 前端设置页每个 Provider 卡片新增「测试连通性」按钮，**无需先保存**即可测试，结果以绿/红卡片展示

**如何使用**：
- 打开「设置」→ LLM Provider 配置区 → 填好配置 → 点「测试连通性」
- 成功：绿色「✓ 连通成功」+ 响应预览
- 失败：红色「✗ 连通失败」+ 配置提示（如「api_base 可能缺少 /v1 后缀」）+ 详细错误（如「HTTP 401 未授权」）
- 右栏分析失败时也会直接显示 `llm_error` 诊断信息

**典型场景（DeepSeek 配置）**：
- ❌ 错误：`api_base = ` `` `https://api.deepseek.com` ``（带反引号、缺 `/v1`），`model = deepseek-v4-flash`
- ✅ 正确：`api_base = https://api.deepseek.com/v1`，`model = deepseek-chat`
- 现在程序会自动清理反引号并提示补 `/v1`，点「测试连通性」即可看到明确诊断

### 修复 2：解密目录检测不到 → 扩大扫描范围

**问题**：用户把 wechat-decrypt 克隆在 `~/Study/wechat-decrypt/`，解密结果在 `~/Study/wechat-decrypt/decrypted/`，但原自动检测只扫到家目录和 wechat-ui 同级目录，检测不到。

**改动文件**：
- [backend/auto_setup.py](backend/auto_setup.py)

**具体变更**：
1. `auto_detect_decrypted_dir()` 新增第 4 步：扫描开发目录
2. 新增 `_dev_dir_candidates()`：返回 `~/Study/`、`~/Projects/`、`~/code/`、`~/workspace/`、`~/work/`、`~/dev/`、`~/repos/`、`~/src/`、`~/github/`、`~/Code/` 等开发目录
3. 新增 `_scan_dev_dirs_for_decrypted()`：在开发目录下查找 `wechat-decrypt/decrypted`、`wechat-decrypt-ref/decrypted`、`wechat_decrypt/decrypted` 以及直接放在开发目录下的 `decrypted/`
4. `_wechat_decrypt_dir_candidates()` 同步扩展：在开发目录下查找 wechat-decrypt 项目（用于增量解密和 config.json 读取）

**如何使用**：
- 无需任何操作，自动检测会自动扫描这些开发目录
- 把 wechat-decrypt 克隆在 `~/Study/wechat-decrypt/` 后，点「设置 → 🔍 自动检测」即可找到
- 也可通过环境变量指定：`export WECHAT_DECRYPT_DIR=/path/to/wechat-decrypt`

### 修复 3：没有增量解密触发入口 → 新增端点 + 前端按钮

**问题**：原代码虽在启动时自动调 `decrypt_db.py -i` 增量解密，但运行中微信有新消息后，没有手动触发增量同步的入口，只能重启后端或点「自动检测」（会重新跑完整检测流程）。

**改动文件**：
- [backend/main.py](backend/main.py)
- [frontend/src/components/Settings.tsx](frontend/src/components/Settings.tsx)
- [frontend/src/api/client.ts](frontend/src/api/client.ts)
- [frontend/src/types/index.ts](frontend/src/types/index.ts)

**具体变更**：
1. 新增 `POST /api/decrypt/incremental` 端点：复用 `auto_setup.try_auto_decrypt()` 逻辑（调用 `decrypt_db.py -i`），只解密新消息，不重新解密联系人库
2. 成功后自动把新的 `decrypted_dir` 写回配置并重置 reader 缓存（无需重启即可看到新消息）
3. 返回标准结构：`{ok, decrypted_dir, decrypted_count, message}`
4. 前端设置页「数据目录」标题栏新增「⬆ 增量同步」按钮，点击后显示同步结果（成功/失败 + 解密数量 + 解密目录）

**如何使用**：
- 微信有新消息后，打开「设置」→ 数据目录 → 点「⬆ 增量同步」
- 程序会调用 wechat-decrypt 的 `decrypt_db.py -i` 只拉取新消息
- 完成后自动刷新配置，回到主界面即可看到最新消息
- 失败时会显示原因（如「未找到 wechat-decrypt 项目目录」「未找到密钥文件 all_keys.json」）

> 注意：增量同步需要 wechat-decrypt 项目目录和 `all_keys.json` 密钥文件就绪。macOS 首次使用需先完成密钥提取（见 Q1）。

### 测试

新增 23 个测试覆盖上述修复（总计 66 个，全部通过）：
- `TestLLMErrorHandling`（16 个）：api_base 清理、/v1 检测、HTTP 错误诊断、错误透传
- `TestAPIExtra`（5 个）：`/api/llm/test` 和 `/api/decrypt/incremental` 端点
- `TestAutoSetup` 新增 2 个：开发目录扫描

```bash
cd wechat-ui
python -m pytest tests/ -v          # 66 passed
cd frontend && npx tsc --noEmit     # 0 errors
cd frontend && npm run build        # ✓ built
```

---

## 许可与免责

- 本项目仅用于浏览**已解密**的本人微信数据，不涉及任何解密/破解行为
- 解密请使用 wechat-decrypt 并遵守其许可
- 请勿用于侵犯他人隐私或非法用途
