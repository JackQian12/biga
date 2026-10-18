# -*- coding: utf-8 -*-
"""联网搜索服务（可插拔）。

默认实现 WebScrapeSearchProvider——按用户选择使用"百度/必应搜索 + 自建爬虫抓取"，
无需第三方 API key：
  1. 请求搜索引擎结果页（bing/baidu）
  2. 解析出候选结果链接，按 top_k 取前 N 个
  3. 抓取每个链接页面正文，提取摘要作为 LLM 的实时上下文

如搜索结果因反爬被限，可用 mock provider 本地演示。provider 通过 config 配置切换。
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..config import SearchCfg
from ..utils import http_utils

logger = logging.getLogger(__name__)


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str = "", content: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.content = content

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "content": self.content[:3000],  # 控制上下文大小
        }


class SearchProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[SearchResult]: ...


def _extract_content_from_html(html: str, limit: int = 2000) -> str:
    """从网页 HTML 提取主干文本作为正文摘要。"""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = soup.body or soup
    text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
    return text[:limit]


class WebScrapeSearchProvider(SearchProvider):
    """自建爬虫：必应/百度结果页 + 正文抓取，带反爬机制。"""

    # 搜索引擎→结果链接选择器
    LINK_SELECTORS = {
        "bing": ["li.b_algo h2 a", "h2 a"],
        "baidu": [".result h3 a", "#content_left h3 a", "h3.t a", "h3 a"],
    }
    # 搜索结果摘要
    SNIPPET_SELECTORS = {
        "bing": ["li.b_algo .b_caption p", "li.b_algo p"],
        "baidu": [".result .c-abstract", ".result .c-span-last ", ".result .c-row"],
    }

    def __init__(self, cfg: SearchCfg):
        self.cfg = cfg
        self.engine = (cfg.engine or cfg.provider or "bing").lower()
        self._engines = [self.engine] + [e for e in ("bing", "baidu") if e != self.engine]
        # 反爬抓取器：UA 轮换、代理、退避重试、随机延迟
        self.fetcher = http_utils.Fetcher(
            user_agents=[cfg.user_agent] if cfg.user_agent else (cfg.user_agents or None),
            proxy_url=cfg.proxy_url,
            timeout=cfg.timeout,
            retries=cfg.retries,
            backoff=cfg.backoff,
            enable_delay=cfg.enable_delay,
            min_delay=cfg.min_delay,
            max_delay=cfg.max_delay,
            referer="https://www.baidu.com/" if self.engine == "baidu" else "https://www.bing.com/",
        )

    @property
    def name(self) -> str:
        return f"webscrape-{self.engine}"

    def _search_url(self, query: str, engine: str) -> str:
        q = urllib.parse.quote(query)
        if engine == "baidu":
            return f"https://www.baidu.com/s?wd={q}&rn={self.cfg.top_k}"
        return f"https://www.bing.com/search?q={q}&count={self.cfg.top_k}&setlang=zh-CN"

    def _result_links(self, soup, engine: str) -> List[Dict[str, str]]:
        selectors = self.cfg.result_selector or self.LINK_SELECTORS.get(engine, self.LINK_SELECTORS["bing"])
        if isinstance(selectors, str):
            selectors = [selectors]
        return http_utils.extract_links(soup, selectors, base_url="")

    def _snippets(self, soup, engine: str) -> List[str]:
        selectors = self.cfg.snippet_selector or self.SNIPPET_SELECTORS.get(engine, self.SNIPPET_SELECTORS["bing"])
        if isinstance(selectors, str):
            selectors = [selectors]
        parts = []
        for sel in selectors:
            for el in soup.select(sel):
                t = http_utils.clean_text(el.get_text(" ", strip=True))
                if t:
                    parts.append(t)
        return parts

    def _scrape_engine(self, engine: str, query: str, top_k: int) -> List[SearchResult]:
        url = self._search_url(query, engine)
        logger.info("抓取搜索页 [%s]：%s", engine, url)
        try:
            html = self.fetcher.fetch_html(url)
        except Exception as exc:
            logger.warning("[%s] 搜索页抓取失败：%s", engine, exc)
            return []
        soup = http_utils.parse(html)
        links = self._result_links(soup, engine)
        snippets = self._snippets(soup, engine)

        results: List[SearchResult] = []
        for i, link in enumerate(links[:top_k]):
            snippet = snippets[i] if i < len(snippets) else ""
            results.append(SearchResult(link["title"], link["url"], snippet=snippet))

        # 抓取前 N 个链接正文（可选）
        if self.cfg.fetch_content:
            for r in results[:top_k]:
                try:
                    body = self.fetcher.fetch_html(r.url)
                    r.content = _extract_content_from_html(body)
                except Exception as exc:
                    logger.warning("抓取正文失败 %s：%s", r.url, exc)
                    r.content = ""
        return results

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        top_k = top_k or self.cfg.top_k
        last_exc: Exception | None = None
        for engine in self._engines:
            try:
                results = self._scrape_engine(engine, query, top_k)
                if results:
                    return results
            except Exception as exc:
                last_exc = exc
                logger.warning("[%s] 搜索失败，尝试兜底引擎：%s", engine, exc)
        if last_exc:
            raise last_exc
        return []


class MockSearchProvider(SearchProvider):
    """本地 mock，用于无网络环境下演示与联调。"""

    @property
    def name(self) -> str:
        return "mock"

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        return [
            SearchResult(
                title=f"（mock）{query} - 结果 {i}",
                url=f"https://example.com/?q={urllib.parse.quote(query)}&i={i}",
                snippet=f"这是本地 mock 搜索命中，条 {i}。不会真实联网，供接口联调。",
                content=f"（mock 正文）关于 {query} 的第 {i} 条示例内容，用于演示搜索上下文如何注入 LLM。",
            )
            for i in range(1, max(1, top_k) + 1)
        ]


def create_search_provider(cfg: SearchCfg) -> SearchProvider:
    provider = (cfg.provider or cfg.engine or "bing").lower()
    if provider == "mock":
        return MockSearchProvider()
    return WebScrapeSearchProvider(cfg)
