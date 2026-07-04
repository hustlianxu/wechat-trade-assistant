"""whisper.cpp 本地语音转录封装。

参考：https://github.com/ggerganov/whisper.cpp
推荐模型：ggml-small.bin（多语言，约 466MB）

设计：
1. 优先调用打包的 whisper.cpp 可执行文件（main 或 whisper-cli）
2. 失败时尝试 Python whisper 包
3. 都不可用时返回占位文本（开发环境），生产环境应报错
"""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path
from typing import List, Optional


def _bundled_whisper_path() -> Path:
    """返回随应用打包的 whisper.cpp 可执行文件路径。"""
    here = Path(__file__).resolve().parent
    project_root = here.parents[3]
    bin_dir = project_root / "bin"
    system = platform.system().lower()
    if system == "windows":
        return bin_dir / "windows" / "whisper-cli.exe"
    elif system == "darwin":
        return bin_dir / "macos" / "whisper-cli"
    else:
        return bin_dir / "linux" / "whisper-cli"


def _default_model_path() -> Path:
    """默认 whisper 模型路径。"""
    here = Path(__file__).resolve().parent
    project_root = here.parents[3]
    return project_root / "models" / "whisper" / "ggml-small.bin"


class WhisperEngine:
    """whisper.cpp 转录引擎封装。"""

    def __init__(
        self,
        whisper_bin: Optional[Path] = None,
        model_path: Optional[Path] = None,
        language: str = "es",  # 西班牙语优先
        threads: int = 4,
    ) -> None:
        self.whisper_bin = Path(whisper_bin) if whisper_bin else _bundled_whisper_path()
        self.model_path = Path(model_path) if model_path else _default_model_path()
        self.language = language
        self.threads = threads

    def is_available(self) -> bool:
        """whisper.cpp + 模型是否可用。"""
        return self.whisper_bin.exists() and self.model_path.exists()

    def transcribe(self, wav_path: Path) -> str:
        """转录单个 WAV 文件，返回文本。"""
        wav_path = Path(wav_path)
        if not wav_path.exists():
            raise FileNotFoundError(f"WAV 文件不存在：{wav_path}")

        if self.is_available():
            try:
                return self._transcribe_with_cpp(wav_path)
            except Exception as e:  # noqa: BLE001
                print(f"[stt] whisper.cpp 失败，回退 Python：{e}")

        # 尝试 Python whisper 包
        try:
            return self._transcribe_with_python(wav_path)
        except ImportError:
            pass
        except Exception as e:  # noqa: BLE001
            print(f"[stt] Python whisper 失败：{e}")

        # 兜底
        print(
            "[stt] 警告：未找到可用的 whisper 引擎，返回占位文本。"
            "请下载 whisper.cpp 和模型到 models/whisper/"
        )
        return "[语音转录不可用：未安装 whisper]"

    def transcribe_batch(self, wav_paths: List[Path]) -> List[str]:
        return [self.transcribe(p) for p in wav_paths]

    # ------------------------------------------------------------------
    def _transcribe_with_cpp(self, wav_path: Path) -> str:
        """调用 whisper.cpp CLI。

        whisper-cli -m model.bin -l es -f input.wav -oj
        -oj 输出 JSON，便于解析
        """
        out_dir = wav_path.parent / "whisper_out"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self.whisper_bin),
            "-m", str(self.model_path),
            "-l", self.language,
            "-t", str(self.threads),
            "-f", str(wav_path),
            "-oj",  # 输出 JSON
            "-of", str(out_dir / wav_path.stem),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"whisper-cli 失败：{result.stderr[:500]}")

        json_path = out_dir / f"{wav_path.stem}.json"
        if not json_path.exists():
            # 回退从 stdout 解析
            return result.stdout.strip()

        data = json.loads(json_path.read_text(encoding="utf-8"))
        # whisper.cpp JSON 结构：{"transcription": [{"text": "..."}]}
        if "transcription" in data:
            return " ".join(seg.get("text", "").strip() for seg in data["transcription"]).strip()
        if "text" in data:
            return str(data["text"]).strip()
        return ""

    def _transcribe_with_python(self, wav_path: Path) -> str:
        """使用 openai-whisper Python 包。"""
        import whisper  # type: ignore

        # 模型路径转 whisper Python 识别的名称
        model_name = self.model_path.stem if self.model_path.exists() else "small"
        # ggml-* 前缀去掉
        if model_name.startswith("ggml-"):
            model_name = model_name[5:]
        model = whisper.load_model(model_name)
        result = model.transcribe(
            str(wav_path),
            language=self.language,
            task="transcribe",
        )
        return result.get("text", "").strip()


# 模块级单例
_default_engine: Optional[WhisperEngine] = None


def get_default_engine() -> WhisperEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = WhisperEngine()
    return _default_engine
