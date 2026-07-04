"""语音转录模块。

对外暴露：
- WhisperEngine：whisper.cpp 封装
- convert_silk_to_wav：SILK → WAV 转换
- transcribe_voice_message：完整流水线（SILK → WAV → 文本）
"""

from pathlib import Path
from typing import List, Optional

from .silk_converter import convert_silk_to_wav
from .whisper_engine import WhisperEngine, get_default_engine


def transcribe_voice_message(
    silk_path: Path,
    engine: Optional[WhisperEngine] = None,
    cache_dir: Optional[Path] = None,
) -> str:
    """完整的语音转录流水线：SILK → WAV → 文本。

    Args:
        silk_path: 微信语音文件路径
        engine: whisper 引擎，为空则用默认
        cache_dir: WAV 缓存目录，为空则与 silk 同目录

    Returns:
        转录后的文本
    """
    if engine is None:
        engine = get_default_engine()

    # 1. SILK → WAV
    if cache_dir is not None:
        wav_path = cache_dir / (Path(silk_path).stem + ".wav")
    else:
        wav_path = Path(silk_path).with_suffix(".wav")

    if not wav_path.exists():
        convert_silk_to_wav(Path(silk_path), wav_path)

    # 2. WAV → 文本
    return engine.transcribe(wav_path)


def transcribe_voice_messages_batch(
    silk_paths: List[Path],
    engine: Optional[WhisperEngine] = None,
    cache_dir: Optional[Path] = None,
) -> List[str]:
    """批量转录。"""
    return [
        transcribe_voice_message(p, engine=engine, cache_dir=cache_dir)
        for p in silk_paths
    ]


__all__ = [
    "WhisperEngine",
    "get_default_engine",
    "convert_silk_to_wav",
    "transcribe_voice_message",
    "transcribe_voice_messages_batch",
]
