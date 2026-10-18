# -*- coding: utf-8 -*-
"""企业微信推送：自建应用渠道 + 群机器人加签 的单元测试（mock 传输层）。"""
from __future__ import annotations

import json

import pytest

from app.config import WecomCfg
from app.notify import wecom as wcmod


class FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def __repr__(self):  # pragma: no cover
        return f"<FakeResp {json.dumps(self._data, ensure_ascii=False)}>"


class FakeClient:
    """记录调用并按 URL 分派：gettoken -> token；message/send -> errcode=0。"""

    def __init__(self, timeout=15):
        self.calls = []
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls.append({"method": "get", "url": url, "params": params})
        if "gettoken" in url:
            return FakeResp({"errcode": 0, "access_token": "TOKEN_ABC", "expires_in": 7200})
        return FakeResp({"errcode": 0})

    def post(self, url, json=None, params=None):
        self.calls.append({"method": "post", "url": url, "json": json, "params": params})
        return FakeResp({"errcode": 0, "msgid": "MSG_1"})


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(wcmod.httpx, "Client", lambda *a, **k: client)
    # 清空 token 缓存，避免脏数据
    monkeypatch.setattr(wcmod, "_token_cache", {})
    return client


@pytest.fixture
def app_notifier(app_config):
    return wcmod.WecomNotifier(app_config.wecom)


def test_app_notifier_has_app_and_enabled(app_notifier):
    assert app_notifier.has_app is True
    assert app_notifier.enabled is True


def test_app_send_markdown_injects_token_and_body(app_notifier, fake_client):
    app_notifier.send_markdown("### 测试日报\n正文内容")
    posts = [c for c in fake_client.calls if c["method"] == "post"]
    assert len(posts) == 1
    p = posts[0]
    assert "message/send" in p["url"]
    assert p["params"]["access_token"] == "TOKEN_ABC"
    body = p["json"]
    assert body["touser"] == "@all"
    assert body["agentid"] == 1000002
    assert body["safe"] == 0
    assert body["msgtype"] == "markdown"
    assert "测试日报" in body["markdown"]["content"]


def test_app_token_cached(app_notifier, fake_client):
    app_notifier.send_text("a")
    app_notifier.send_text("b")
    gets = [c for c in fake_client.calls if c["method"] == "get"]
    assert len(gets) == 1  # 令牌只拉取一次并被缓存


def test_app_send_text_touser_override(app_notifier, fake_client):
    app_notifier.send_text("hi", touser="zhangsan")
    body = [c for c in fake_client.calls if c["method"] == "post"][0]["json"]
    assert body["touser"] == "zhangsan"


def test_webhook_signature_url():
    notifier = wcmod.WecomNotifier(WecomCfg(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                                            webhook_secret="SECRET"))
    url = notifier._signed_url(notifier.cfg.webhook_url, "SECRET")
    assert "timestamp=" in url and "sign=" in url
    prefix = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc&"
    assert url.startswith(prefix)
    ts, sign = None, None
    for part in url[len(prefix):].split("&"):
        k, _, v = part.partition("=")
        if k == "timestamp":
            ts = v
        elif k == "sign":
            sign = v
    assert ts and sign
    import base64, hashlib, hmac as h
    msg = f"{ts}\nSECRET".encode()
    expect = base64.b64encode(h.new(msg, digestmod=hashlib.sha256).digest()).hex()
    assert sign == expect


def test_webhook_channel_when_configured(monkeypatch):
    cfg = WecomCfg(enabled=True,
                   webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc")
    n = wcmod.WecomNotifier(cfg)
    client = FakeClient()
    monkeypatch.setattr(wcmod.httpx, "Client", lambda *a, **k: client)
    n.send_markdown("x")
    assert client.calls and client.calls[0]["method"] == "post"
    assert "webhook/send" in client.calls[0]["url"]
    assert client.calls[0]["json"]["msgtype"] == "markdown"


def test_app_notifier_disabled_without_any_channel():
    n = wcmod.WecomNotifier(WecomCfg(enabled=True))
    assert n.enabled is False
