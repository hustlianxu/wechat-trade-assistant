# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：把 backend 包及其依赖打包成可独立运行的可执行文件。

产出（--name wta-backend）：
    dist-python/
        wta-backend          (macOS/Linux 可执行入口)
        wta-backend.exe      (Windows 可执行入口)
        _internal/           (PyInstaller 6+ 依赖目录)
        backend/             (backend 包源码 + schema.sql)
        ... 各依赖库

打包后整个 dist-python 目录由 electron-builder 作为 extraResources 复制进
应用的 resources/backend-runtime，由 electron/python_runner.ts 在生产态启动。

入口说明：
    使用 launcher.py 而非 main.py 作为入口。main.py 用了相对导入
    (from .api.routes import)，作为顶层脚本执行会报 ImportError。
    launcher.py 先把 src/ 加入 sys.path，再用绝对导入调用 backend.main.run()。

使用：
    cd <项目根>
    pyinstaller installers/backend.spec --noconfirm \\
        --distpath dist-python --workpath build/pyi
"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 收集动态导入的子模块（intent/stt 等模块用了延迟导入）
hiddenimports = []
try:
    hiddenimports += collect_submodules('backend')
except Exception:
    # 首次打包时 backend 可能不在默认 sys.path，靠 pathex 补
    pass
hiddenimports += [
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.loops.auto',
]

# 数据文件：schema.sql 必须随包
datas = [
    ('../src/backend/storage/schema.sql', 'backend/storage'),
]

a = Analysis(
    ['../src/backend/launcher.py'],
    pathex=['../src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 排除未启用的大依赖，减小体积（whisper/transformers 走外部二进制）
        'torch', 'transformers', 'tensorflow', 'numpy', 'pandas',
        'matplotlib', 'PIL', 'tkinter',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='wta-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='wta-backend',
)
