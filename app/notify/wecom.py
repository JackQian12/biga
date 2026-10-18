# -*- coding: utf-8 -*-
"""企业微信推送服务（支持两种渠道）。

渠道 1 —— 群机器人 Webhook：
  1. 普通群机器人（未加签）：直接 POST webhook_url
  2. 加签群机器人：webhook_url 末尾需拼 &timestamp= 与 &sign=（HMAC-SHA256 签名）

渠道 2 —— 自建应用消息（corpid/agentid/app_secret）：
  1. GET /cgi-bin/gettoken 换取 access_token（带缓存）
  2. POST /cgi-bin/message/send 推送给 touser（默认 @all 全员）

消息类型：text / markdown（两个渠道均支持）。发送后校验 errcode==0 才算成功。

渠道选择规则：配置了 webhook_url 优先走渠道 1；否则若配置了应用凭据则走渠道 2，
由 send_text/send_markdown 自动分发。渠道 2 可传入 touser 覆盖全局 app_touser。

注意：本模块只负责推送，订阅数据（自选股、接收对象）由调度/路由层传入。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from threading import Lock
from typing import Any, Dict

import httpx

from ..config import WecomCfg

logger = logging.getLogger(__name__)

_QYAPI = "https://qyapi.weixin.qq.com"
_token_cache: Dict[str, tuple] = {}   # (corpid,secret) -> (access_token, expires_at)
_token_lock = Lock()


def _get_token(corpid: str, app_secret: str) -> str:
    """获取/缓存应用 access_token，过期自动刷新。"""
    key = f"{corpid}|{app_secret}"
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
    params = {"corpid": corpid, "corpsecret": app_secret}
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{_QYAPI}/cgi-bin/gettoken", params=params)
        resp.raise_for_status()
        data = resp.json()
    if data.get("errcode") != 0 or not data.get("access_token"):
        raise RuntimeError(f"获取企业微信 access_token 失败：{data}")
    with _token_lock:
        _token_cache[key] = (data["access_token"],
                             time.time() + int(data.get("expires_in", 7200)))
    return data["access_token"]


class WecomNotifier:
    def __init__(self, cfg: WecomCfg):
        self.cfg = cfg

    @property
    def has_app(self) -> bool:
        c = self.cfg
        return bool(c.corpid and c.agentid and c.app_secret)

    @property
    def enabled(self) -> bool:
        c = self.cfg
        return bool(c.enabled and (c.webhook_url or self.has_app))

    # ---------- 渠道 1：群机器人 ----------
    @staticmethod
    def _signed_url(webhook_url: str, secret: str = "") -> str:
        if not secret:
            return webhook_url
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).hex()
        sep = "&" if "?" in webhook_url else "?"
        return f"{webhook_url}{sep}timestamp={timestamp}&sign={sign}"

    def _post_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.cfg.webhook_url:
            raise RuntimeError("未配置 webhook_url，无法走群机器人渠道")
        url = self._signed_url(self.cfg.webhook_url, self.cfg.webhook_secret)
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return _ok_or_raise("群机器人", data)

    # ---------- 渠道 2：应用消息 ----------
    def _post_app(self, payload: Dict[str, Any], touser: str = None) -> Dict[str, Any]:
        if not self.has_app:
            raise RuntimeError("未配置 corpid/agentid/app_secret，无法走应用消息渠道")
        body = {
            "touser": touser or self.cfg.app_touser or "@all",
            "agentid": int(self.cfg.agentid),
            "safe": 0,
        }
        body.update(payload)
        token = _get_token(self.cfg.corpid, self.cfg.app_secret)
        with httpx.Client(timeout=15) as client:
            resp = client.post(f"{_QYAPI}/cgi-bin/message/send",
                               params={"access_token": token}, json=body)
            resp.raise_for_status()
            data = resp.json()
        return _ok_or_raise("应用消息", data)

    # ---------- 统一入口：按渠道自动分发 ----------
    def send_text(self, text: str, touser: str = None) -> Dict[str, Any]:
        if self.cfg.webhook_url:
            return self._post_webhook({"msgtype": "text", "text": {"content": text}})
        return self._post_app({"msgtype": "text", "text": {"content": text}}, touser=touser)

    def send_markdown(self, content: str, touser: str = None) -> Dict[str, Any]:
        if self.cfg.webhook_url:
            return self._post_webhook({"msgtype": "markdown", "markdown": {"content": content}})
        return self._post_app({"msgtype": "markdown", "markdown": {"content": content}}, touser=touser)


def _ok_or_raise(channel: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if data.get("errcode") != 0:
        raise RuntimeError(f"企业微信{channel}返回错误：{data}")
    return data


def create_notifier(cfg: WecomCfg) -> WecomNotifier:
    return WecomNotifier(cfg)
