#!/usr/bin/env bash
# 准备原生二进制资产：sqlcipher（解密微信数据库必需）。
#
# 解密微信 4.0.x 数据库需要 SQLCipher。pysqlcipher3 是 C 扩展，在不同平台
# 编译困难且 PyInstaller 打包易出问题。本脚本改为下载/编译独立的 sqlcipher
# CLI 二进制放入 bin/<platform>/，运行时由后端 _find_sqlcipher_binary() 查找。
#
# 支持平台：macos (arm64/x64)、linux、windows
#
# 用法：
#   bash installers/prepare_native_assets.sh          # 当前平台
#   PLATFORM=macos ARCH=arm64 bash installers/prepare_native_assets.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 自动检测平台和架构
OS_TYPE="$(uname -s)"
case "$OS_TYPE" in
  Darwin) PLATFORM="${PLATFORM:-macos}" ;;
  Linux)  PLATFORM="${PLATFORM:-linux}" ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM="${PLATFORM:-windows}" ;;
  *) echo "不支持的平台：$OS_TYPE"; exit 1 ;;
esac

ARCH="${ARCH:-$(uname -m)}"
case "$ARCH" in
  x86_64|amd64) ARCH="x64" ;;
  arm64|aarch64) ARCH="arm64" ;;
esac

BIN_DIR="$PROJECT_ROOT/bin"
mkdir -p "$BIN_DIR/$PLATFORM"

echo "=========================================="
echo " 准备原生二进制资产 ($PLATFORM/$ARCH)"
echo "=========================================="

# ----------------------------------------------------------------------------
# sqlcipher
# ----------------------------------------------------------------------------
SQLCIPHER_BIN="$BIN_DIR/$PLATFORM/sqlcipher"
if [ "$PLATFORM" = "windows" ]; then
  SQLCIPHER_BIN="$BIN_DIR/$PLATFORM/sqlcipher.exe"
fi

if [ -x "$SQLCIPHER_BIN" ]; then
  echo "[sqlcipher] 已存在: $SQLCIPHER_BIN"
else
  echo "[sqlcipher] 准备 sqlcipher 二进制..."

  # 策略 1：优先用 Homebrew（macOS）或系统已安装的 sqlcipher
  if command -v sqlcipher >/dev/null 2>&1; then
    SYS_BIN="$(command -v sqlcipher)"
    echo "[sqlcipher] 复制系统 sqlcipher: $SYS_BIN → $SQLCIPHER_BIN"
    cp "$SYS_BIN" "$SQLCIPHER_BIN"
    chmod +x "$SQLCIPHER_BIN" 2>/dev/null || true
    # macOS：复制动态库依赖（sqlcipher 依赖 libcrypto、libsqlite3 等）
    if [ "$PLATFORM" = "macos" ]; then
      echo "[sqlcipher] 检查动态库依赖..."
      otool -L "$SQLCIPHER_BIN" 2>/dev/null | grep -v "/usr/lib\|/System" | head -10 || true
    fi
  fi

  # 策略 2：macOS 用 brew install sqlcipher（会安装到非标准路径）
  if [ ! -x "$SQLCIPHER_BIN" ] && [ "$PLATFORM" = "macos" ]; then
    if command -v brew >/dev/null 2>&1; then
      echo "[sqlcipher] 用 Homebrew 安装 sqlcipher..."
      brew install sqlcipher 2>/dev/null || true
      # brew 安装的 sqlcipher 在 /opt/homebrew/bin 或 /usr/local/bin
      for p in "/opt/homebrew/bin/sqlcipher" "/usr/local/bin/sqlcipher"; do
        if [ -x "$p" ]; then
          cp "$p" "$SQLCIPHER_BIN"
          chmod +x "$SQLCIPHER_BIN"
          echo "[sqlcipher] 已从 $p 复制到 $SQLCIPHER_BIN"
          break
        fi
      done
    fi
  fi

  # 策略 3：从源码编译（最通用，但需要 openssl-dev / build-essential）
  if [ ! -x "$SQLCIPHER_BIN" ]; then
    echo "[sqlcipher] 尝试从源码编译..."
    TMP_BUILD="$(mktemp -d)"
    SQLCIPHER_VERSION="4.5.5"
    SQLCIPHER_URL="https://github.com/sqlcipher/sqlcipher/archive/refs/tags/v${SQLCIPHER_VERSION}.tar.gz"

    if command -v curl >/dev/null 2>&1; then
      curl -sL "$SQLCIPHER_URL" -o "$TMP_BUILD/sqlcipher.tar.gz"
    elif command -v wget >/dev/null 2>&1; then
      wget -q "$SQLCIPHER_URL" -O "$TMP_BUILD/sqlcipher.tar.gz"
    else
      echo "[sqlcipher] 警告：无 curl/wget，无法下载源码"
    fi

    if [ -f "$TMP_BUILD/sqlcipher.tar.gz" ]; then
      tar -xzf "$TMP_BUILD/sqlcipher.tar.gz" -C "$TMP_BUILD"
      SRC_DIR="$TMP_BUILD/sqlcipher-${SQLCIPHER_VERSION}"
      cd "$SRC_DIR"

      # 编译参数：静态链接，避免运行时缺动态库
      if [ "$PLATFORM" = "macos" ]; then
        # macOS：用 openssl@1.1 或 openssl@3
        OPENSSL_DIR=""
        for p in "/opt/homebrew/opt/openssl@3" "/opt/homebrew/opt/openssl@1.1" "/usr/local/opt/openssl@3" "/usr/local/opt/openssl@1.1"; do
          if [ -d "$p" ]; then
            OPENSSL_DIR="$p"
            break
          fi
        done
        if [ -n "$OPENSSL_DIR" ]; then
          export CFLAGS="-I${OPENSSL_DIR}/include"
          export LDFLAGS="-L${OPENSSL_DIR}/lib"
        fi
        ./configure --enable-tempstore=yes --disable-tcl \
          --with-crypto-lib=commoncrypto 2>/dev/null || \
          ./configure --enable-tempstore=yes --disable-tcl
      else
        ./configure --enable-tempstore=yes --disable-tcl \
          --with-crypto-lib=openssl 2>/dev/null || \
          ./configure --enable-tempstore=yes --disable-tcl
      fi

      make -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)" sqlite3.c sqlite3.h || make sqlite3.c sqlite3.h
      # 编译独立的 shell（即 sqlcipher CLI）
      gcc -DSQLITE_HAS_CODEC -DSQLITE_TEMP_STORE=2 \
        -I. shell.c sqlite3.c \
        -o "$SQLCIPHER_BIN" \
        $([ "$PLATFORM" = "macos" ] && echo "-framework Security -framework CoreFoundation" || echo "-lcrypto") \
        2>/dev/null || gcc -DSQLITE_HAS_CODEC -I. shell.c sqlite3.c -o "$SQLCIPHER_BIN" -lcrypto 2>/dev/null || true

      cd "$PROJECT_ROOT"
      chmod +x "$SQLCIPHER_BIN" 2>/dev/null || true
      rm -rf "$TMP_BUILD"
    fi
  fi

  # 最终检查
  if [ -x "$SQLCIPHER_BIN" ]; then
    echo "[sqlcipher] ✓ 已准备: $SQLCIPHER_BIN"
    "$SQLCIPHER_BIN" --version 2>/dev/null | head -1 || true
  else
    echo "[sqlcipher] ✗ 未能准备 sqlcipher 二进制"
    echo "[sqlcipher] 用户需手动安装："
    echo "  macOS:  brew install sqlcipher"
    echo "  Ubuntu: sudo apt install sqlcipher"
    echo "  Windows: 从 https://github.com/sqlcipher/sqlcipher/releases 下载"
    echo "[sqlcipher] 或运行时安装 pysqlcipher3: pip install pysqlcipher3"
    # 不 exit 1，允许继续打包（解密功能不可用但其他功能仍可用）
  fi
fi

echo ""
echo "原生资产准备完成。bin/$PLATFORM/ 内容："
ls -la "$BIN_DIR/$PLATFORM/" 2>/dev/null || echo "(空)"
