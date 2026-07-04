#!/usr/bin/env bash
# 下载/准备随应用打包的原生资源：whisper.cpp 二进制 + 西班牙语语音模型
#
# 产出目录布局：
#   bin/
#     whisper-cli           (macOS/Linux)  或 whisper-cli.exe (Windows)
#     silk_decoder          (可选，SILK→WAV；若没有则后端用纯 Python 兜底)
#   models/
#     whisper/
#       ggml-small.bin      (~466 MB，多语种，西语识别效果好)
#       ggml-tiny.bin       (~75 MB，可选轻量备选)
#     intent/
#       (Intento-v1-xlmr 由 transformers 动态加载，体积大，默认不打包；
#        未下载时后端自动走 rule_fallback 规则引擎，详见 backend/intent/)
#
# 用法：
#   bash installers/prepare_native_assets.sh           # 下载默认模型
#   MODEL=ggml-tiny.bin bash installers/prepare_native_assets.sh  # 轻量模型
#
# 说明：whisper.cpp 没有官方预编译发行版覆盖全部平台，建议各平台自行编译：
#   git clone https://github.com/ggerganov/whisper.cpp
#   cd whisper.cpp && cmake -B build && cmake --build build -j
#   # 产物在 build/bin/whisper-cli，复制到项目 bin/ 并按平台命名

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

MODEL="${MODEL:-ggml-small.bin}"
BIN_DIR="$PROJECT_ROOT/bin"
MODELS_DIR="$PROJECT_ROOT/models/whisper"
INTENT_DIR="$PROJECT_ROOT/models/intent"

mkdir -p "$BIN_DIR" "$MODELS_DIR" "$INTENT_DIR"

OS="$(uname -s)"
case "$OS" in
  Darwin) WHISPER_BIN_NAME="whisper-cli" ;;
  Linux)  WHISPER_BIN_NAME="whisper-cli" ;;
  MINGW*|MSYS*|CYGWIN*) WHISPER_BIN_NAME="whisper-cli.exe" ;;
  *) echo "未知系统：$OS"; exit 1 ;;
esac

echo "=========================================="
echo " 准备原生资源"
echo "=========================================="
echo " 平台: $OS  二进制名: $WHISPER_BIN_NAME"
echo " 模型: $MODEL"
echo ""

# 1. whisper.cpp 二进制
WHISPER_BIN="$BIN_DIR/$WHISPER_BIN_NAME"
if [ -x "$WHISPER_BIN" ]; then
  echo "[1/3] whisper-cli 已存在，跳过"
else
  echo "[1/3] 未找到 whisper-cli，请按下方提示手动编译并放到 $WHISPER_BIN"
  echo "      git clone https://github.com/ggerganov/whisper.cpp"
  echo "      cd whisper.cpp && cmake -B build && cmake --build build -j"
  echo "      cp build/bin/whisper-cli $WHISPER_BIN"
  echo "      （不放置也可运行，语音转录会自动降级到占位实现）"
fi

# 2. 下载 whisper 模型
MODEL_PATH="$MODELS_DIR/$MODEL"
if [ -f "$MODEL_PATH" ]; then
  echo "[2/3] 模型已存在，跳过: $MODEL_PATH"
else
  URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL"
  echo "[2/3] 下载模型: $URL"
  echo "      → $MODEL_PATH"
  if command -v curl >/dev/null; then
    curl -L --fail -o "$MODEL_PATH" "$URL" || {
      echo "下载失败，请手动下载：$URL"
      rm -f "$MODEL_PATH"
    }
  elif command -v wget >/dev/null; then
    wget -O "$MODEL_PATH" "$URL" || {
      echo "下载失败，请手动下载：$URL"
      rm -f "$MODEL_PATH"
    }
  else
    echo "缺少 curl/wget，请手动下载：$URL"
  fi
fi

# 3. Intento 意图模型（可选，体积大，默认跳过）
echo "[3/3] Intento-v1-xlmr 意图模型（可选）"
echo "      默认不下载；后端在缺失时自动使用规则兜底引擎（rule_fallback）。"
echo "      如需启用，手动执行："
echo "        git clone https://huggingface.co/luigicfilho/Intento-v1-xlmr $INTENT_DIR/Intento-v1-xlmr"
echo ""

echo "=========================================="
echo " 完成"
echo "=========================================="
echo " bin/        : $(ls -1 "$BIN_DIR" 2>/dev/null | tr '\n' ' ')"
echo " models/whisper/: $(ls -1 "$MODELS_DIR" 2>/dev/null | tr '\n' ' ')"
