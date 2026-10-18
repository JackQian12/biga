# -*- coding: utf-8 -*-
"""LLM 服务（OpenAI 兼容端点客户端）。

用于把你的本地 OpenAI 兼容端点 http://192.168.50.46:8888/v1 集成进来。
模型名/密钥可配置；不传模型时由端点决定。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import httpx

from ..config import LLMCfg

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, cfg: LLMCfg):
        self.cfg = cfg
        self._endpoint = cfg.base_url.rstrip("/")

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        return h

    def chat(self, messages: List[Dict[str, Any]], **overrides) -> Dict[str, Any]:
        """调用 /chat/completions。返回标准 OpenAI 响应结构。"""
        url = f"{self._endpoint}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "stream": False,
        }
        payload.update(overrides)  # 运行时可覆盖 max_tokens 等
        if not payload.get("model"):
            # 本地端点通常要求显式 model；留空时清掉，避免发送空字符串被部分端点拒绝。
            del payload["model"]

        logger.debug("调用 LLM：POST %s", url)
        with httpx.Client(timeout=self.cfg.timeout) as client:
            resp = client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            # 兼容不同封装结构：可能直接返回 content
            if "choices" not in data and "content" in data:
                return {"choices": [{"message": {"content": data["content"]}}], "model": data.get("model", self.cfg.model)}
            return data

    def complete(self, prompt: str, **overrides) -> str:
        """简化接口：输入一个 prompt，返回补全文本。"""
        messages = [{"role": "user", "content": prompt}]
        data = self.chat(messages, **overrides)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("无法从 LLM 响应解析内容：%s", data)
            raise RuntimeError(f"LLM 响应格式异常: {data}") from exc
