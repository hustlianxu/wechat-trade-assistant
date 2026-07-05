"""语音转录：SILK → WAV → whisper.cpp 本地优先 + LLM 兜底。

流程：
1. 从 media_*.db 读取 SILK 语音数据
2. SILK → WAV 转换（pysilk 或 ffmpeg）
3. 优先用 whisper.cpp 本地转录
4. 本地失败时用配置的 LLM（OpenAI Whisper API 或兼容接口）兜底
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional


def silk_to_wav(silk_data: bytes, sample_rate: int = 24000) -> bytes:
    """将 SILK 音频数据转换为 WAV 格式。

    优先用 pysilk 库，回退到 silk-v3-decoder 命令行工具。
    """
    # 方案 1：pysilk 库
    try:
        import pysilk
        pcm_data = pysilk.decode(silk_data, sample_rate)
        return _pcm_to_wav(pcm_data, sample_rate)
    except ImportError:
        pass

    # 方案 2：silk_v3_decoder 命令行（silk_v3_decoder）
    try:
        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as silk_file:
            silk_file.write(silk_data)
            silk_path = silk_file.name
        wav_path = silk_path.replace(".silk", ".wav")
        result = subprocess.run(
            ["silk_v3_decoder", silk_path, wav_path],
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode == 0 and os.path.exists(wav_path):
            with open(wav_path, "rb") as f:
                return f.read()
    except FileNotFoundError:
        pass
    finally:
        for p in (silk_path, wav_path):
            try:
                os.unlink(p)
            except (NameError, OSError):
                pass

    # 方案 3：ffmpeg（如果 SILK 被 ffmpeg 支持，某些版本可以）
    try:
        with tempfile.NamedTemporaryFile(suffix=".silk", delete=False) as silk_file:
            silk_file.write(silk_data)
            silk_path = silk_file.name
        wav_path = silk_path.replace(".silk", ".wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", silk_path, "-ar", str(sample_rate),
             "-ac", "1", "-f", "wav", wav_path],
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode == 0 and os.path.exists(wav_path):
            with open(wav_path, "rb") as f:
                return f.read()
    except FileNotFoundError:
        pass
    finally:
        for p in (silk_path, wav_path):
            try:
                os.unlink(p)
            except (NameError, OSError):
                pass

    raise RuntimeError(
        "SILK → WAV 转换失败。请安装依赖之一：pip install pysilk，或 silk_v3_decoder，或 ffmpeg"
    )


def _pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """PCM 原始数据转 WAV 格式。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(bits // 8)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_data)
    return buf.getvalue()


# ============================================================================
# whisper.cpp 本地转录
# ============================================================================
def transcribe_with_whisper_cpp(
    wav_data: bytes,
    binary_path: str,
    model_path: str,
    language: str = "",
) -> Optional[str]:
    """用 whisper.cpp 命令行转录。

    whisper.cpp 使用方式：
        whisper-cpp -m <model> -f <wav_file> [-l <language>]

    返回转录文本，失败返回 None。
    """
    if not binary_path or not Path(binary_path).exists():
        return None
    if not model_path or not Path(model_path).exists():
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
        wav_file.write(wav_data)
        wav_path = wav_file.name

    try:
        cmd = [binary_path, "-m", model_path, "-f", wav_path, "--no-timestamps"]
        if language:
            cmd.extend(["-l", language])
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            return None
        # whisper.cpp 输出格式：每行 "[时间戳] 文本"
        # 用 --no-timestamps 后输出是纯文本
        text = result.stdout.strip()
        # 清理：去掉可能的行首时间戳标记
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("whisper_"):
                # 去掉 "[0000:00:00.000 --> 0000:00:00.000]" 格式的时间戳
                if line.startswith("[") and "]" in line:
                    line = line.split("]", 1)[-1].strip()
                if line:
                    lines.append(line)
        return " ".join(lines) if lines else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


# ============================================================================
# LLM 兜底转录（OpenAI Whisper API 兼容）
# ============================================================================
def transcribe_with_llm(
    wav_data: bytes,
    llm_config: dict,
) -> Optional[str]:
    """用 LLM 的语音转录 API（OpenAI Whisper 兼容接口）转录。

    llm_config 格式：
        {
            "name": "openai",
            "api_base": "https://api.openai.com/v1",
            "api_key": "sk-...",
            "model": "whisper-1"
        }
    """
    import urllib.request
    import urllib.error
    import json
    import uuid

    api_base = llm_config.get("api_base", "").rstrip("/")
    api_key = llm_config.get("api_key", "")
    model = llm_config.get("model", "whisper-1")

    if not api_base or not api_key:
        return None

    # 构造 multipart/form-data 请求
    boundary = uuid.uuid4().hex
    filename = f"audio_{uuid.uuid4().hex[:8]}.wav"

    body = b""
    # model 字段
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="model"\r\n\r\n'.encode()
    body += f"{model}\r\n".encode()
    # file 字段
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    body += b"Content-Type: audio/wav\r\n\r\n"
    body += wav_data
    body += f"\r\n--{boundary}--\r\n".encode()

    url = f"{api_base}/audio/transcriptions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("text", "").strip()
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return None


# ============================================================================
# 统一转录入口
# ============================================================================
def transcribe_voice(
    silk_data: bytes,
    whisper_config: dict,
    llm_config: Optional[dict] = None,
) -> tuple[str, str]:
    """转录语音，返回 (文本, 来源)。

    来源："whisper_cpp" | "llm" | "error"

    流程：
    1. SILK → WAV
    2. 优先 whisper.cpp 本地转录
    3. 本地失败时用 LLM 兜底
    4. 全部失败返回错误信息
    """
    # 1. SILK → WAV
    try:
        wav_data = silk_to_wav(silk_data)
    except Exception as e:
        return f"[语音转换失败：{e}]", "error"

    # 2. whisper.cpp 本地转录
    text = transcribe_with_whisper_cpp(
        wav_data,
        binary_path=whisper_config.get("binary_path", ""),
        model_path=whisper_config.get("model_path", ""),
        language=whisper_config.get("language", ""),
    )
    if text:
        return text, "whisper_cpp"

    # 3. LLM 兜底
    if llm_config:
        text = transcribe_with_llm(wav_data, llm_config)
        if text:
            return text, "llm"

    return "[语音转录失败：本地 whisper.cpp 和 LLM 均不可用]", "error"
