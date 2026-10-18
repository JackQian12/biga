# -*- coding: utf-8 -*-
"""服务容器：持有数据源、LLM、搜索的共享单例，便于各路由/调度复用并支持重载。"""
from __future__ import annotations

from typing import Optional

from .config import AppConfig, get_config
from .datasource import create_data_source
from .datasource.base import DataSource
from .services.llm import LLMClient
from .services.search import SearchProvider, create_search_provider

_datasource: Optional[DataSource] = None
_llm: Optional[LLMClient] = None
_search: Optional[SearchProvider] = None


def reset() -> None:
    global _datasource, _llm, _search
    _datasource = _llm = _search = None


def get_datasource(config: AppConfig | None = None) -> DataSource:
    global _datasource
    cfg = config or get_config()
    if _datasource is None or _datasource.name != cfg.data_source.provider:
        _datasource = create_data_source(cfg.data_source.provider, cfg.data_source.tushare_token)
    return _datasource


def get_llm(config: AppConfig | None = None) -> LLMClient:
    global _llm
    cfg = config or get_config()
    if _llm is None or _llm.endpoint != cfg.llm.base_url.rstrip("/"):
        _llm = LLMClient(cfg.llm)
    return _llm


def get_search(config: AppConfig | None = None) -> SearchProvider:
    global _search
    cfg = config or get_config()
    if _search is None or _search.name != f"webscrape-{cfg.search.engine}" and not (
        cfg.search.engine in {"baidu", "bing"} and _search.name == "mock"
    ):
        _search = create_search_provider(cfg.search)
    return _search
