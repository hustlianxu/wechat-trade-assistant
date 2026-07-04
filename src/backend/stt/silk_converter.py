"""SILK → WAV 转换器。

微信语音使用 SILK 编码（由 Skype 开发），需要转成 PCM/WAV 才能给 whisper.cpp 处理。

实现策略：
1. 优先调用打包好的 silk_v3_decoder（C 编译产物，随应用分发）
2. 失败时尝试 Python silk-python 包
3. 都不可用时返回占位 WAV（用于开发/沙箱），并打印警告

参考：
- https://github.com/kn007/silk-v3-decoder
- wechat-decrypt 项目里的 silk 解码逻辑
"""

from __future__ import annotations

import io
import os
import platform
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Optional


# 打包后 silk_decoder 的预期路径
def _bundled_decoder_path() -> Path:
    """返回随应用打包的 silk_decoder 可执行文件路径。"""
    env = os.environ.get("WTA_BIN_DIR")
    if env:
        bin_dir = Path(env).expanduser().resolve()
    else:
        # 复用 config 模块的路径逻辑
        from ..config import get_bin_dir
        bin_dir = get_bin_dir()
    system = platform.system().lower()
    if system == "windows":
        return bin_dir / "windows" / "silk_v3_decoder.exe"
    elif system == "darwin":
        # Apple Silicon / Intel 都用同一个二进制（universal binary）
        return bin_dir / "macos" / "silk_v3_decoder"
    else:
        return bin_dir / "linux" / "silk_v3_decoder"


def _is_silk(data: bytes) -> bool:
    """判断字节流是否为 SILK 格式。

    SILK 文件头：#!SILK_V3（标准）或 #!SILK_V3\x00（微信变体）
    """
    if not data:
        return False
    if data.startswith(b"#!SILK_V3"):
        return True
    return False


def _strip_silk_header(data: bytes) -> bytes:
    """去掉 SILK 头部（前 9 或 10 字节），返回纯 SILK 帧。"""
    if data.startswith(b"#!SILK_V3\x00"):
        return data[10:]
    if data.startswith(b"#!SILK_V3"):
        return data[9:]
    return data


def _pcm_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """把 PCM 字节流包装成 WAV 格式。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def convert_silk_to_wav(
    silk_path: Path,
    output_path: Optional[Path] = None,
    sample_rate: int = 24000,
) -> Path:
    """把 SILK 文件转换为 WAV。返回 WAV 文件路径。

    Args:
        silk_path: 输入 SILK 文件
        output_path: 输出 WAV 路径；为空则与输入同目录、.wav 后缀
        sample_rate: 采样率（微信语音通常 24000Hz）
    """
    silk_path = Path(silk_path)
    if not silk_path.exists():
        raise FileNotFoundError(f"SILK 文件不存在：{silk_path}")

    if output_path is None:
        output_path = silk_path.with_suffix(".wav")
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = silk_path.read_bytes()
    if not _is_silk(data):
        # 不是 SILK，可能是已经解密过的 PCM 或 WAV，直接复制
        if data.startswith(b"RIFF") and b"WAVE" in data[:16]:
            shutil.copyfile(silk_path, output_path)
            return output_path
        # 当作裸 PCM
        wav_bytes = _pcm_to_wav(data, sample_rate=sample_rate)
        output_path.write_bytes(wav_bytes)
        return output_path

    # 1. 尝试打包的 C 解码器
    decoder = _bundled_decoder_path()
    if decoder.exists():
        try:
            return _convert_with_c_decoder(decoder, silk_path, output_path)
        except Exception as e:  # noqa: BLE001
            print(f"[stt] C 解码器失败，回退 Python：{e}")

    # 2. 尝试 Python silk 包
    try:
        return _convert_with_python_silk(silk_path, output_path, sample_rate)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"[stt] Python silk 解码失败：{e}")

    # 3. 兜底：生成空 WAV 占位（开发环境用，生产环境应报错）
    print(
        "[stt] 警告：未找到可用的 SILK 解码器，生成占位 WAV。"
        "请安装 silk_v3_decoder 或 pip install pysilk"
    )
    _write_silence_wav(output_path, duration_sec=1.0, sample_rate=sample_rate)
    return output_path


def _convert_with_c_decoder(decoder: Path, silk_path: Path, output_path: Path) -> Path:
    """调用 C 编译的 silk_v3_decoder。

    该工具通常用法：./silk_v3_decoder input.silk output.pcm
    然后再用 PCM → WAV。
    """
    pcm_path = output_path.with_suffix(".pcm")
    cmd = [str(decoder), str(silk_path), str(pcm_path)]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode != 0 or not pcm_path.exists():
        raise RuntimeError(f"silk_v3_decoder 失败：{result.stderr}")

    pcm = pcm_path.read_bytes()
    wav = _pcm_to_wav(pcm, sample_rate=24000)
    output_path.write_bytes(wav)
    try:
        pcm_path.unlink()
    except OSError:
        pass
    return output_path


def _convert_with_python_silk(silk_path: Path, output_path: Path, sample_rate: int) -> Path:
    """使用 pysilk-mod 解码。"""
    import pysilk  # type: ignore

    data = silk_path.read_bytes()
    pcm = pysilk.decode(data, 24000)
    wav = _pcm_to_wav(pcm, sample_rate=24000)
    output_path.write_bytes(wav)
    return output_path


def _write_silence_wav(path: Path, duration_sec: float, sample_rate: int = 24000) -> None:
    """写一个静音 WAV（开发兜底）。"""
    n_samples = int(duration_sec * sample_rate)
    silence = b"\x00\x00" * n_samples
    wav = _pcm_to_wav(silence, sample_rate=sample_rate)
    path.write_bytes(wav)
