# -*- coding: utf-8 -*-
"""联网搜索爬虫提供方 + 反爬机制的单元测试（mock 抓取器）。"""
from __future__ import annotations

from app.config import SearchCfg
from app.services import search as search_mod
from app.services.search import MockSearchProvider, WebScrapeSearchProvider

_BING_HTML = """
<html><body>
<ol>
  <li class="b_algo"><h2><a href="https://news.example.com/1">贵州茅台季报</a></h2>
      <div class="b_caption"><p>茅台发布季报，净利同比增长。</p></div></li>
  <li class="b_algo"><h2><a href="https://news.example.com/2">券商研报</a></h2>
      <div class="b_caption"><p>多家券商看好春节消费。</p></div></li>
</ol>
</body></html>
"""

_BAIDU_HTML = """
<html><body>
<div id="content_left">
  <div class="result"><h3><a href="https://news.example.com/3">百度结果三</a></h3>
     <div class="c-abstract">百度摘要三</div></div>
  <div class="result"><h3><a href="https://news.example.com/4">百度结果四</a></h3>
     <div class="c-abstract">百度摘要四</div></div>
</div>
</body></html>
"""

_EMPTY = "<html><body></body></html>"

_ARTICLE_HTML = """
<html><body>
<article><h1>标题</h1><p>这是一段正文。</p></article>
<footer>页脚</footer><nav>导航</nav>
</body></html>
"""


class _FakeFetcher:
    """按 URL 分派返回 HTML 的伪抓取器，记录被请求的 URL。"""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def fetch_html(self, url, **kwargs):
        self.calls.append(url)
        return self.handler(url)


def _make_provider(cfg=None, engine="bing"):
    sc = cfg or SearchCfg(provider=engine, engine=engine, retries=2, backoff=1.0,
                          enable_delay=False)
    return WebScrapeSearchProvider(sc)


def test_bing_parse_and_content(app_config):
    provider = _make_provider(engine="bing")

    def handler(url):
        if "bing.com/search" in url:
            return _BING_HTML
        return _ARTICLE_HTML  # 正文页

    provider.fetcher = _FakeFetcher(handler)
    results = provider.search("茅台风报", top_k=2)
    assert len(results) == 2
    assert results[0].title == "贵州茅台季报"
    assert results[0].url == "https://news.example.com/1"
    assert "净利同比增长" in results[0].snippet
    # fetch_content=True 会抓正文
    assert any("这是一段正文" in r.content for r in results)


def test_engine_fallback_when_primary_empty(app_config):
    provider = _make_provider(engine="bing")

    def handler(url):
        if "bing.com/search" in url:
            return _EMPTY  # 必应无结果 → 触发兜底
        if "baidu.com/s" in url:
            return _BAIDU_HTML
        return _ARTICLE_HTML

    provider.fetcher = _FakeFetcher(handler)
    # 首选 bing 拿不到结果 → 自动兜底 baidu
    results = provider.search("百度测试", top_k=2)
    assert len(results) == 2
    assert results[0].url == "https://news.example.com/3"
    urls = provider.fetcher.calls
    assert any("baidu.com/s" in u for u in urls)


def test_mock_provider(app_config):
    p = MockSearchProvider()
    assert p.name == "mock"
    results = p.search("贵州茅台", top_k=3)
    assert len(results) == 3
    assert all(r.title.startswith("（mock）") for r in results)


def test_anti_crawler_config_passthrough():
    sc = SearchCfg(provider="bing", engine="bing",
                   user_agents=["ua-a", "ua-b"], proxy_url="http://127.0.0.1:7890",
                   retries=4, backoff=2.0, enable_delay=True, min_delay=0.1, max_delay=0.2)
    p = _make_provider(sc)
    f = p.fetcher
    assert f.user_agents == ["ua-a", "ua-b"]
    assert f.retries == 4
    assert f.backoff == 2.0
    assert f.enable_delay is True
    assert f.max_delay == 0.2
    assert f.proxy_url == "http://127.0.0.1:7890"


def test_create_provider_mock_vs_web():
    assert isinstance(search_mod.create_search_provider(SearchCfg(provider="mock")),
                      MockSearchProvider)
    assert isinstance(search_mod.create_search_provider(SearchCfg(provider="bing")),
                      WebScrapeSearchProvider)
