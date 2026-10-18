# -*- coding: utf-8 -*-
"""订阅管理路由 + 手动/调度推送（走自建应用渠道）的集成测试。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as cfgmod
import app.database as db
from app.notify import wecom as wcmod
from app.routers import wecom as wecom_router


class _FakeLLM:
    def complete(self, prompt):
        return "### 📈 A股情报日报\n自选股解读内容"


class _FakeSearch:
    class _R:
        def __init__(self, title, url):
            self.title = title
            self.url = url
            self.snippet = f"{title} 摘要"
            self.content = f"{title} 正文"

    def search(self, query, top_k=5):
        return [self._R(f"{query} 结果{i}", f"https://example.com/{i}") for i in range(min(3, top_k))]


class _FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, timeout=15):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls.append(("get", url, params))
        return _FakeResp({"errcode": 0, "access_token": "TOKEN_SUB", "expires_in": 7200})

    def post(self, url, json=None, params=None):
        self.calls.append(("post", url, json, params))
        return _FakeResp({"errcode": 0, "msgid": "X"})

    def posts(self):
        return [c for c in self.calls if c[0] == "post"]

@pytest.fixture
def client(app_config, monkeypatch):
    # 仅注入 subscriptions 路由的轻量 app（不启动调度器/数据源）。
    # 路由自带 Depends(verify_token)，verify_token 依赖 get_config() → 我们的单例。
    app = FastAPI()
    app.include_router(wecom_router.router)
    monkeypatch.setattr(cfgmod, "_config_singleton", app_config)
    return TestClient(app)


def _seed_subscription(app_config, enabled=True):
    return db.add_subscription(name="测试分组", webhook_url="",
                               watch_codes=["600519", "000001"], enabled=enabled)


def _patch_env(monkeypatch, app_config):
    fake_llm = _FakeLLM()
    fake_search = _FakeSearch()
    monkeypatch.setattr("app.services.push.get_llm", lambda cfg: fake_llm)
    monkeypatch.setattr("app.services.push.get_search", lambda cfg: fake_search)
    monkeypatch.setattr("app.services.analyze.get_llm", lambda cfg: fake_llm)
    monkeypatch.setattr("app.services.analyze.get_search", lambda cfg: fake_search)
    fake_client = _FakeClient()
    monkeypatch.setattr(wcmod.httpx, "Client", lambda *a, **k: fake_client)
    monkeypatch.setattr(wcmod, "_token_cache", {})
    return fake_client



# ---------- 路由：认证 ----------
def test_subscriptions_require_auth(client):
    r = client.get("/api/v1/subscriptions")
    assert r.status_code == 401


# ---------- 路由：CRUD ----------
def test_crud_flow(client, app_config, monkeypatch):
    fake_client = _patch_env(monkeypatch, app_config)
    headers = {"Authorization": "Bearer change-me-token-1"}

    r = client.post("/api/v1/subscriptions", headers=headers, json={
        "name": "测试分组", "webhook_url": "", "watch_codes": ["600519"]})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["watch_codes"] == ["600519"]

    assert client.get("/api/v1/subscriptions", headers=headers).status_code == 200
    assert client.get(f"/api/v1/subscriptions/{sid}", headers=headers).json()["name"] == "测试分组"

    r = client.patch(f"/api/v1/subscriptions/{sid}", headers=headers,
                     json={"watch_codes": ["600519", "000001"], "enabled": False})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["watch_codes"] == ["600519", "000001"]

    assert client.delete(f"/api/v1/subscriptions/{sid}", headers=headers).json()["deleted"] == sid
    assert client.get(f"/api/v1/subscriptions/{sid}", headers=headers).status_code == 404


# ---------- 手动推送：走应用渠道 ----------
def test_push_to_subscription_via_app_channel(app_config, monkeypatch):
    fake_client = _patch_env(monkeypatch, app_config)
    from app.services.push import push_to_subscription
    sid = _seed_subscription(app_config)
    sub = db.get_subscription(sid)
    result = push_to_subscription(app_config, sub)
    assert result["status"] == "ok"
    posts = fake_client.posts()
    assert len(posts) == 1
    body = posts[0][2]
    assert body["msgtype"] == "markdown"
    assert "解读内容" in body["markdown"]["content"]
    assert posts[0][1].endswith("/cgi-bin/message/send")


def test_push_analysis_via_app_channel(app_config, monkeypatch):
    fake_client = _patch_env(monkeypatch, app_config)
    from app.services.push import push_analysis
    sid = _seed_subscription(app_config)
    sub = db.get_subscription(sid)
    result = push_analysis(app_config, sub, code="600519", question="今天怎么看",
                           use_search=True, top_k=3)
    assert result["status"] == "ok"
    posts = fake_client.posts()
    assert len(posts) == 1
    assert "600519" in posts[0][2]["markdown"]["content"]


def test_push_all(app_config, monkeypatch):
    fake_client = _patch_env(monkeypatch, app_config)
    from app.services.push import push_all
    _seed_subscription(app_config)
    results = push_all(app_config)
    assert len(results) == 1
    assert results[0]["status"] == "ok"


def test_disabled_without_app_and_webhook(app_config, monkeypatch):
    app_config.wecom.corpid = ""
    app_config.wecom.agentid = ""
    app_config.wecom.app_secret = ""
    app_config.wecom.webhook_url = ""
    fake_client = _patch_env(monkeypatch, app_config)
    from app.services.push import push_to_subscription
    sid = _seed_subscription(app_config)
    sub = db.get_subscription(sid)
    result = push_to_subscription(app_config, sub)
    assert result["status"] == "disabled"
    assert fake_client.posts() == []


# ---------- 调度触发 ----------
def test_push_daily_scheduler_trigger(app_config, monkeypatch):
    fake_client = _patch_env(monkeypatch, app_config)
    from app.scheduler import push_daily
    _seed_subscription(app_config)
    result = push_daily(app_config)
    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert fake_client.posts(), "调度日报应走应用渠道发送消息"


def test_push_daily_disabled_when_wecom_off(app_config, monkeypatch):
    app_config.wecom.enabled = False
    _patch_env(monkeypatch, app_config)
    from app.scheduler import push_daily
    result = push_daily(app_config)
    assert result["status"] == "disabled"
