# -*- coding: utf-8 -*-
"""数据源抽象基类。

具体实现通过延迟 import 外部库（akshare/tushare），因此即使这些库未安装，
FastAPI 应用也可以正常启动；只有真正调用数据接口时才会报错，提示安装。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class DataSource(ABC):
    """数据源抽象：行情、基本面、新闻三大类能力。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def check_available(self) -> str:
        """返回依赖是否就绪的提示。"""
        return "ok"

    @abstractmethod
    def fetch_quotes(self) -> List[Dict[str, Any]]:
        """返回全市场最新行情快照列表。"""

    @abstractmethod
    def fetch_fundamentals(self) -> List[Dict[str, Any]]:
        """返回全市场基本面快照列表。"""

    def fetch_news(self, codes: List[str] | None = None) -> List[Dict[str, Any]]:
        """返回新闻；子类可 override 从上游取（akshare 一般无全市场新闻接口，
        因此默认子类先从本地库/搜索层借力，这里返回空并由调度器回退到搜索新闻）。"""
        return []

    # ---------- 多维度报告所需的可选扩展数据 ----------
    # 子类可按需实现；默认返回空列表，调用方需容忍空结果并给出兜底文案。

    def fetch_funds_flow(self, codes: List[str]) -> List[Dict[str, Any]]:
        """返回个股资金流向（主力/超大单/大单/中单/小单净流入等）。"""
        return []

    def fetch_shareholders(self, codes: List[str]) -> List[Dict[str, Any]]:
        """返回个股股本结构（总股本/流通股本/股东户数等）。"""
        return []

    def fetch_technical(self, codes: List[str]) -> List[Dict[str, Any]]:
        """返回个股技术指标（换手率/量比/MA/RSI/MACD 等）。"""
        return []
