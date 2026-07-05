"""微信媒体文件解析器：将图片 / 语音 / 文件消息解析为实际文件路径。

微信 4.x 的非文本消息（图片、语音、文件、视频）的内容以 XML 存放
在 message_content 中，实际文件分散在多个位置：
  - 图片: cache/YYYY-MM/Message/<md5>/Bubble/<hash>_b.dat（XOR 加密）
  - 语音: message/media_N.db/VoiceInfo 表（SILK BLOB）
  - 文件: msg/attach/ 或 msg/file/ 目录
  - 视频: msg/video/ 目录

本模块提供统一的媒体文件解析入口，在消息导入后调用。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
import wave
from pathlib import Path
from typing import Optional

from ..storage.models import Message
from .image_decoder import decrypt_dat_image

# ---------------------------------------------------------------------------
# SILK → WAV 转换（依赖 pilk 库，纯 Python 无需外部二进制）
# ---------------------------------------------------------------------------
def silk_to_wav(silk_data: bytes, output_path: Path) -> Optional[Path]:
    """将 SILK 语音数据转换为 WAV 文件。

    使用 pilk 库解码 SILK → PCM，再用 Python wave 模块写入 WAV。
    无需外部 ffmpeg 或 silk_decoder 二进制。

    Args:
        silk_data: 原始 SILK 字节（来自 VoiceInfo.voice_data）。
        output_path: 输出 WAV 文件路径（*.wav）。

    Returns:
        转换成功返回 output_path，否则回退为 .silk 文件。
    """
    import tempfile
    import wave

    # SILK 格式检查与修复
    if not silk_data or len(silk_data) < 20:
        return None

    if silk_data.startswith(b"#!SILK_V3"):
        pass  # 标准 SILK 头
    else:
        pos = silk_data.find(b"#!SILK_V3")
        if pos >= 0:
            silk_data = silk_data[pos:]
        else:
            # 无 SILK 头，回退保存原始数据
            fallback = output_path.with_suffix(".silk")
            fallback.write_bytes(silk_data)
            return None

    # 添加结尾结束符（pilk 要求）
    if not silk_data.endswith(b"\xff\xff"):
        silk_data += b"\xff\xff"

    tmp_silk = Path(tempfile.mktemp(suffix=".silk"))
    tmp_pcm = Path(tempfile.mktemp(suffix=".pcm"))
    try:
        tmp_silk.write_bytes(silk_data)

        # 使用 pilk 解码 SILK → PCM（16位 24000Hz 单声道）
        try:
            import pilk
            pilk.decode(str(tmp_silk), str(tmp_pcm))
        except ImportError:
            # pilk 未安装，回退保存 .silk
            fallback = output_path.with_suffix(".silk")
            tmp_silk.rename(fallback)
            return None

        if not tmp_pcm.exists() or tmp_pcm.stat().st_size < 100:
            return None

        # 写入 WAV（Python 标准库，无需 ffmpeg）
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)          # 单声道
            wf.setsampwidth(2)           # 16 位 = 2 bytes
            wf.setframerate(24000)        # 24kHz（微信 SILK 常用采样率）
            wf.writeframes(tmp_pcm.read_bytes())

        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path

        # 回退：保存 PCM
        fallback = output_path.with_suffix(".pcm")
        tmp_pcm.rename(fallback)
        return fallback

    except Exception:
        if not output_path.exists():
            fallback = output_path.with_suffix(".silk")
            try:
                tmp_silk.rename(fallback)
                return fallback
            except Exception:
                pass
        return None
    finally:
        for p in (tmp_silk, tmp_pcm):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 图片解析
# ---------------------------------------------------------------------------
def find_image_in_cache(
    aeskey: str,
    wechat_base_dir: Path,
    assets_dir: Path,
) -> Optional[Path]:
    """通过 aeskey 在微信缓存目录中查找并解密图片。

    微信 4.x 图片存储路径：
      cache/<YYYY-MM>/Message/<md5>/Bubble/<hash>_b.dat

    通过遍历 cache 下所有 Message/*/Bubble/*.dat 文件尝试匹配已知 aeskey
    并非直接的方法。更可靠的方案是配合 message_resource.db 中的映射。
    """
    # 尝试从 message_resource.db 反查
    # 实际上 message_content 中的 aeskey 不一定直接对应文件名,
    # 所以需要全文搜索 cache 目录

    dat_path = _find_dat_by_aeskey(aeskey, wechat_base_dir)
    if dat_path is None:
        return None

    out_dir = assets_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{aeskey}.jpg"

    if not out_path.exists():
        try:
            decrypt_dat_image(dat_path, out_path)
        except Exception:
            return None

    return out_path if out_path.exists() else None


def _find_dat_by_aeskey(aeskey: str, wechat_base_dir: Path) -> Optional[Path]:
    """通过 aeskey 在缓存目录中搜索对应的 .dat 文件。

    搜索策略：
    1. 如果 aeskey 本身就是文件名 (不带扩展名)，直接查找 .dat
    2. 否则遍历 cache/YYYY-MM/Message/*/Bubble/*.dat
    """
    cache_dir = wechat_base_dir / "cache"
    if not cache_dir.exists():
        return None

    # 策略1：尝试直接按 aeskey 找
    for pattern in (f"**/{aeskey}.dat", f"**/{aeskey}_*.dat", f"**/*{aeskey}*.dat"):
        matches = sorted(cache_dir.rglob(pattern))
        if matches:
            return matches[0]

    # 策略2：遍历所有 .dat 文件（回退）
    for dat_path in sorted(cache_dir.rglob("*.dat")):
        if dat_path.stat().st_size < 100:
            continue
        try:
            decrypt_dat_image(dat_path, output_path=dat_path.with_suffix(".tmp.jpg"))
            # 验证解密成功
            decrypted = dat_path.with_suffix(".tmp.jpg")
            if decrypted.exists():
                decrypted.unlink()
                return dat_path
        except Exception:
            continue

    return None


def parse_image_xml(xml_content: str) -> dict:
    """从图片消息 XML 中提取元数据。"""
    result: dict = {}
    m = re.search(r'aeskey="([^"]+)"', xml_content, re.IGNORECASE)
    if m:
        result["aeskey"] = m[1]
    m = re.search(r'cdnmidimgurl="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["cdnmidimgurl"] = m[1]
    m = re.search(r'cdnbigimgurl="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["cdnbigimgurl"] = m[1]
    m = re.search(r'length="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["length"] = m[1]
    return result


# ---------------------------------------------------------------------------
# 语音解析
# ---------------------------------------------------------------------------
def find_voice_in_media_db(
    msg_id: str,
    media_db_conn: sqlite3.Connection,
    assets_dir: Path,
) -> Optional[Path]:
    """在 media_N.db 的 VoiceInfo 表中查找语音数据并转换为 MP3。

    VoiceInfo 表结构：
        chat_name_id, create_time, local_id, svr_id, voice_data BLOB

    svr_id 与消息表 server_id（msg_id）对应。
    """
    try:
        cur = media_db_conn.execute(
            "SELECT voice_data FROM VoiceInfo WHERE svr_id = ?",
            (int(msg_id),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        voice_data = row[0]
        if not voice_data or len(voice_data) < 10:
            return None
    except (sqlite3.Error, ValueError):
        return None

    out_dir = assets_dir / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{msg_id}.wav"

    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    result = silk_to_wav(voice_data, out_path)
    return result


def parse_voice_xml(xml_content: str) -> dict:
    """从语音消息 XML 中提取元数据。"""
    result: dict = {}
    m = re.search(r'aeskey="([^"]+)"', xml_content, re.IGNORECASE)
    if m:
        result["aeskey"] = m[1]
    m = re.search(r'voiceurl="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["voiceurl"] = m[1]
    m = re.search(r'voicelength="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["voicelength"] = m[1]
    m = re.search(r'voiceformat="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["voiceformat"] = m[1]
    m = re.search(r'endflag="([^"]*)"', xml_content, re.IGNORECASE)
    if m:
        result["endflag"] = m[1]
    return result


# ---------------------------------------------------------------------------
# 文件 / 文档解析
# ---------------------------------------------------------------------------
def find_file_in_storage(
    title: str,
    wechat_base_dir: Path,
    assets_dir: Path,
) -> Optional[Path]:
    """在 msg/file/ 或 msg/attach/ 目录中查找文件。

    通过文件名匹配（模糊搜索）。
    """
    out_dir = assets_dir / "files"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 搜索目录
    search_dirs = [
        wechat_base_dir / "msg" / "file",
        wechat_base_dir / "msg" / "attach",
        wechat_base_dir / "resource",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.rglob("*"):
            if not f.is_file() or f.stat().st_size < 10:
                continue
            if title and (title.lower() in f.name.lower()):
                # 复制到 assets
                dest = out_dir / f.name
                if not dest.exists():
                    import shutil
                    shutil.copy2(f, dest)
                return dest

    return None


def parse_appmsg_xml(xml_content: str) -> dict:
    """从 AppMsg（文件/链接/名片）XML 中提取元数据。"""
    result: dict = {}
    m = re.search(r"<title>([^<]*)</title>", xml_content)
    if m:
        result["title"] = m[1]
    m = re.search(r"<des>([^<]*)</des>", xml_content)
    if m:
        result["des"] = m[1]
    m = re.search(r'<type>(\d+)</type>', xml_content)
    if m:
        result["appmsg_type"] = m[1]
    m = re.search(r"<url>([^<]*)</url>", xml_content)
    if m:
        result["url"] = m[1]
    return result


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def resolve_media_for_message(
    msg: Message,
    wechat_base_dir: Path,
    assets_dir: Path,
    media_db_conns: Optional[list[sqlite3.Connection]] = None,
) -> Optional[str]:
    """解析消息的媒体文件，返回本地文件路径。

    Args:
        msg: 已从微信导入的消息对象（含 XML content 和 msg_id）。
        wechat_base_dir: xwechat_files/<wxid> 目录。
        assets_dir: 应用资产缓存目录。
        media_db_conns: 已打开的 media_N.db 连接列表（用于语音查询）。

    Returns:
        解析后的本地文件路径，若无法解析返回 None。
    """
    if msg.msg_type == "text" or not msg.content:
        return None

    if msg.msg_type == "image":
        meta = parse_image_xml(msg.content)
        if "aeskey" in meta:
            result = find_image_in_cache(meta["aeskey"], wechat_base_dir, assets_dir)
            if result:
                return str(result)

    elif msg.msg_type == "voice":
        meta = parse_voice_xml(msg.content)
        # 通过 VoiceInfo 查询（需要 media db 连接）
        if media_db_conns and msg.msg_id:
            for conn in media_db_conns:
                result = find_voice_in_media_db(msg.msg_id, conn, assets_dir)
                if result:
                    return str(result)

    elif msg.msg_type == "file":
        meta = parse_appmsg_xml(msg.content)
        title = meta.get("title", "")
        if title:
            result = find_file_in_storage(title, wechat_base_dir, assets_dir)
            if result:
                return str(result)

    elif msg.msg_type == "video":
        meta = parse_appmsg_xml(msg.content)
        title = meta.get("title", "")
        if title:
            result = find_file_in_storage(title, wechat_base_dir, assets_dir)
            if result:
                return str(result)

    return None


def batch_resolve_media(
    messages: list[Message],
    wechat_base_dir: Path,
    assets_dir: Path,
    media_conns: Optional[list[sqlite3.Connection]] = None,
) -> dict[str, str]:
    """批量解析媒体文件，返回 {msg_id → file_path} 映射。"""
    results: dict[str, str] = {}
    for msg in messages:
        path = resolve_media_for_message(msg, wechat_base_dir, assets_dir, media_conns)
        if path:
            results[msg.msg_id] = path
    return results
