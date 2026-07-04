"""PyInstaller 打包入口启动器。

为什么需要这个文件：
    backend/main.py 使用了相对导入（from .api.routes import ...），
    作为 PyInstaller 的入口脚本直接执行时，Python 把它当成顶层模块，
    没有父包上下文，导致 ImportError: attempted relative import with
    no known parent package。

    本启动器作为顶层入口，先把 src/ 加入 sys.path，再用绝对导入
    from backend.main import main 调用真正的入口函数，
    这样 backend 包内的相对导入就能正常工作。

开发态不受影响（仍然用 python -m backend.main）。
"""

import os
import sys
from pathlib import Path


def _ensure_backend_on_path() -> None:
    """确保 backend 包所在目录在 sys.path 上。

    PyInstaller 打包后，源码会被复制到 _internal/backend/ 或 backend/，
    需要把它的父目录加入 sys.path，Python 才能把 backend 当成包导入。
    """
    # 开发态：src/ 在项目根，launcher.py 位于 src/backend/，父目录即 src/
    # 打包态：PyInstaller 会把 __file__ 指向临时解压目录
    here = Path(__file__).resolve().parent
    # src/backend/launcher.py → src/
    src_dir = here.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    # 打包态兜底：PyInstaller 的 _MEIPASS 解压目录
    meipass = os.environ.get("_MEIPASS")
    if meipass:
        meipass_path = Path(meipass)
        for candidate in (meipass_path, meipass_path / "src", meipass_path.parent):
            if (candidate / "backend").is_dir() and str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
                break


def main() -> None:
    _ensure_backend_on_path()
    # 用绝对导入触发 backend 包的 __init__，相对导入即可正常工作
    # backend/main.py 的入口函数叫 run()
    from backend.main import run as _real_run
    _real_run()


if __name__ == "__main__":
    main()
