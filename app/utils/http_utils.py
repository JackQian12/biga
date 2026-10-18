# -*- coding: utf-8 -*-
"""HTTP 抓取工具（含反爬机制）。

提供 Fetcher 类用于真实网页抓取，内置常见反爬对抗手段：
  * 请求头完整伪装（UA 轮换、Accept-Language、Referer、Accept）
  * 403/429/5xx 指数退避重试 + 随机抖动
  * 可选代理（HTTP/SOCKS 需 requests[socks] 支持）
  * 会话复用（Cookie 保持），降低被风控概率、提升连续抓取命中率
  * 可配置的请求间随机延迟（节流）

同时保留模块级便捷函数 get/fetch_html 供轻量调用。
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

UA_POOL = [
    DEFAULT_UA,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
]

_BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def random_sleep(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """请求间随机休眠，模拟人类抓取节奏，降低被封概率。"""
    time.sleep(random.uniform(min_s, max_s))


class Fetcher:
    """带反爬策略的抓取器。"""

    def __init__(
        self,
        user_agents: Optional[List[str]] = None,
        proxy_url: str = "",
        timeout: int = 15,
        retries: int = 3,
        backoff: float = 1.5,
        enable_delay: bool = True,
        min_delay: float = 0.4,
        max_delay: float = 1.6,
        referer: str = "",
    ):
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.enable_delay = enable_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.referer = referer
        self.proxy_url = proxy_url
        self.user_agents = list(user_agents or UA_POOL)
        self._session = requests.Session()
        self._session.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
        self._ua_index = 0

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = dict(_BASE_HEADERS)
        h["User-Agent"] = self.user_agents[self._ua_index % len(self.user_agents)]
        self._ua_index += 1
        if self.referer:
            h["Referer"] = self.referer
        if extra:
            h.update(extra)
        return h

    def _should_retry(self, status_code: int) -> bool:
        return status_code in (403, 429, 500, 502, 503, 504)

    def get(self, url: str, *, params=None, extra_headers=None, **kwargs) -> requests.Response:
        attempts = self.retries + 1
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            if self.enable_delay and attempt:
                random_sleep(self.min_delay, self.max_delay)
            try:
                resp = self._session.get(
                    url, headers=self._headers(extra_headers), params=params,
                    timeout=self.timeout, **kwargs,
                )
                if self._should_retry(resp.status_code) and attempt < self.retries:
                    wait = self.backoff * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning("%s 返回 %s，%.1fs 后重试 (%d/%d)",
                                   url, resp.status_code, wait, attempt + 1, attempts)
                    time.sleep(wait)
                    continue
                return resp
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    wait = self.backoff * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning("请求 %s 异常（%s），%.1fs 后重试", url, exc, wait)
                    time.sleep(wait)
                    continue
        raise last_exc  # pragma: no cover

    def fetch_html(self, url: str, *, params=None, extra_headers=None) -> str:
        resp = self.get(url, params=params, extra_headers=extra_headers)
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:  # pragma: no cover
            pass

# 模块级便捷接口（保持向后兼容）
_fetcher: Optional[Fetcher] = None


def get(url: str, *, ua: str = "", timeout: int = 15, params=None, **kwargs) -> requests.Response:
    if ua:
        headers = {"User-Agent": ua, **dict(_BASE_HEADERS)}
        return requests.get(url, headers=headers, timeout=timeout, params=params, **kwargs)
    global _fetcher
    if _fetcher is None:
        _fetcher = Fetcher(timeout=timeout)
    return _fetcher.get(url, params=params, extra_headers=kwargs.get("headers"))


def fetch_html(url: str, *, ua: str = "", timeout: int = 15, params=None) -> str:
    resp = get(url, ua=ua, timeout=timeout, params=params)
    resp.raise_for_status()
    return resp.text


def parse(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_links(soup, selectors, base_url: str = "") -> list:
    """从给定 CSS 选择器集合中提取 (title, url) 链接，去重。"""
    links = []
    seen = set()
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href") or ""
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/") and base_url:
                href = base_url.rstrip("/") + href
            title = clean_text(a.get_text())
            if not href or not title or href in seen:
                continue
            if href.lower().startswith(("javascript:", "mailto:")):
                continue
            seen.add(href)
            links.append({"title": title, "url": href})
    return links


def snippets(soup, selectors, limit: int = 200) -> str:
    """把选择器命中的元素文本拼成摘要，作为 LLM 上下文。"""
    parts = []
    for sel in selectors:
        for el in soup.select(sel):
            t = clean_text(el.get_text(" ", strip=True))
            if t:
                parts.append(t)
    return " | ".join(parts)[:limit]
