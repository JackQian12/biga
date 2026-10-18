# -*- coding: utf-8 -*-
"""数据源子包：根据配置返回具体数据源实现（可插拔）。"""
from __future__ import annotations

from .base import DataSource
from .akshare_source import AkShareDataSource
from .tushare_source import TushareDataSource


def create_data_source(provider: str, tushare_token: str = "") -> DataSource:
    provider = (provider or "akshare").lower()
    if provider == "tushare":
        return TushareDataSource(token=tushare_token)
    return AkShareDataSource()

