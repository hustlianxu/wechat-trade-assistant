"""图片 .dat 解密器。

微信图片以 .dat 格式存储，是简单异或加密。
有三种格式变体：
- V1: 单字节异或（最老版）
- V2: 双字节异或
- wxgf: 微信图形格式（4.0 引入，含元数据头）

参考 wechat-decrypt 的 dat_image 模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# JPEG / PNG / GIF 文件头
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GIF_MAGIC = b"GIF87a"
GIF_MAGIC2 = b"GIF89a"


def _detect_xor_byte(data: bytes) -> Optional[int]:
    """根据已知图片文件头反推异或字节。

    微信用 1 字节异或整张图片，所以可以从首字节反推。
    """
    if len(data) < 4:
        return None
    # 尝试 JPEG
    xor = data[0] ^ JPEG_MAGIC[0]
    if (data[1] ^ xor) == JPEG_MAGIC[1] and (data[2] ^ xor) == JPEG_MAGIC[2]:
        return xor
    # 尝试 PNG
    xor = data[0] ^ PNG_MAGIC[0]
    if (data[1] ^ xor) == PNG_MAGIC[1] and (data[2] ^ xor) == PNG_MAGIC[2]:
        return xor
    # 尝试 GIF
    xor = data[0] ^ ord("G")
    if (data[1] ^ xor) == ord("I") and (data[2] ^ xor) == ord("F"):
        return xor
    return None


def decrypt_dat_image(dat_path: Path, output_path: Optional[Path] = None) -> Path:
    """解密微信 .dat 图片文件。

    Args:
        dat_path: .dat 文件路径
        output_path: 输出路径；为空则与输入同目录、自动判断后缀

    Returns:
        解密后的图片文件路径（后缀根据真实格式决定）
    """
    dat_path = Path(dat_path)
    if not dat_path.exists():
        raise FileNotFoundError(f".dat 文件不存在：{dat_path}")

    data = dat_path.read_bytes()
    if not data:
        raise ValueError("空 .dat 文件")

    # 判断是否为 wxgf 格式（4.0）
    if data[:4] == b"wxgf":
        return _decrypt_wxgf(data, dat_path, output_path)

    # V1/V2 异或解密
    xor = _detect_xor_byte(data)
    if xor is None:
        # 无法识别，原样输出为 .bin
        out = output_path or dat_path.with_suffix(".bin")
        out.write_bytes(data)
        return out

    decrypted = bytes(b ^ xor for b in data)

    # 根据文件头决定后缀
    if decrypted.startswith(JPEG_MAGIC):
        suffix = ".jpg"
    elif decrypted.startswith(PNG_MAGIC):
        suffix = ".png"
    elif decrypted.startswith(GIF_MAGIC) or decrypted.startswith(GIF_MAGIC2):
        suffix = ".gif"
    else:
        suffix = ".bin"

    if output_path is None:
        output_path = dat_path.with_suffix(suffix)
    else:
        output_path = Path(output_path)

    output_path.write_bytes(decrypted)
    return output_path


def _decrypt_wxgf(data: bytes, dat_path: Path, output_path: Optional[Path]) -> Path:
    """解密 wxgf 格式（4.0）。

    wxgf 文件结构：
    - 4 字节 magic: "wxgf"
    - 4 字节版本
    - 4 字节长度
    - 4 字节格式标志（1=PNG, 2=JPEG, 3=GIF）
    - 元数据
    - 加密图片数据
    """
    # 简化处理：跳过头部 16 字节后，剩余部分按异或解密
    # 实际实现需参考 wechat-decrypt 的 wxgf 解析
    if len(data) < 16:
        out = output_path or dat_path.with_suffix(".bin")
        out.write_bytes(data)
        return out

    # 读取格式标志（第 12-16 字节，小端）
    fmt_flag = int.from_bytes(data[12:16], "little")
    fmt_suffix_map = {1: ".png", 2: ".jpg", 3: ".gif"}
    suffix = fmt_suffix_map.get(fmt_flag, ".bin")

    # 跳过 header，剩余作为图片数据（wxgf 通常无加密，只是封了一层壳）
    # 真实情况更复杂，需参考 wechat-decrypt
    payload = data[16:]

    if output_path is None:
        output_path = dat_path.with_suffix(suffix)
    else:
        output_path = Path(output_path)

    output_path.write_bytes(payload)
    return output_path
