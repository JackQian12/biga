# -*- coding: utf-8 -*-
"""pytest 共享夹具：隔离数据库、重置单例、构造 app-channel 配置。"""
from __future__ import annotations

import pytest

import app.config as cfgmod
import app.database as dbmod
from app import container
from app.config import AppConfig


@pytest.fixture
def app_config(tmp_path, monkeypatch):
    """构造一份隔离的 AppConfig（sqlite 走临时文件；搜索走 mock；企业微信走自建应用渠道）。"""
    cfg = AppConfig()
    cfg.storage.sqlite_path = str(tmp_path / "test_biga.db")
    cfg.search.provider = "mock"
    cfg.search.engine = "mock"

    # 企业微信自建应用渠道（渠道 2），未配 webhook
    cfg.wecom.enabled = True
    cfg.wecom.corpid = "wwCORPID123"
    cfg.wecom.agentid = "1000002"
    cfg.wecom.app_secret = "SECRET_APP"
    cfg.wecom.app_touser = "@all"
    cfg.wecom.webhook_url = ""
    cfg.wecom.webhook_secret = ""

    # 替换配置单例 & 重置服务/数据库缓存
    monkeypatch.setattr(cfgmod, "_config_singleton", cfg)
    container.reset()
    dbmod._LOCAL.conn = None
    dbmod._LOCAL.db_path = None
    yield cfg
    container.reset()
    dbmod._LOCAL.conn = None
    dbmod._LOCAL.db_path = None
