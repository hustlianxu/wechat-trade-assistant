"""pytest 全局 fixture。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 把 src/ 加入 sys.path，使 backend 包可被 import
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """每个测试用独立的临时数据目录，并重置全局单例。"""
    data_dir = tmp_path / "wta_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WTA_DATA_DIR", str(data_dir))

    # 重置 backend.config 单例
    from backend import config as cfg
    cfg.reset_services()

    yield data_dir

    cfg.reset_services()


@pytest.fixture
def repo(tmp_data_dir):
    """构造一个干净的 Repository。"""
    from backend import config as cfg
    return cfg.get_repo()


@pytest.fixture
def repo_with_mock_data(repo):
    """插入 mock 客户 + 消息的 Repository。"""
    from backend.storage.models import Contact
    from tests.mock_data import MOCK_CONTACTS, build_messages_for_insert

    # 1. 写入联系人
    wxid_to_id = {}
    for c in MOCK_CONTACTS:
        contact = Contact(
            wxid=c["wxid"],
            nickname=c["nickname"],
            remark=c["remark"],
            alias=c["alias"],
            region=c["region"],
            note=c["note"],
        )
        cid = repo.upsert_contact(contact)
        wxid_to_id[c["wxid"]] = cid

    # 2. 写入消息（关联 contact_id）
    msgs_to_insert = []
    for wxid, msg in build_messages_for_insert():
        msg.contact_id = wxid_to_id[wxid]
        msgs_to_insert.append(msg)
    repo.insert_messages_bulk(msgs_to_insert)

    return repo, wxid_to_id
