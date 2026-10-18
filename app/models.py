# -*- coding: utf-8 -*-
"""共享 Pydantic schema（请求/响应模型）"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------- 数据记录 ----------
class QuoteRecord(BaseModel):
    code: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: float
    amount: float
    change_pct: float
    change: float
    update_time: str


class FundamentalsRecord(BaseModel):
    code: str
    name: str
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    market_cap: Optional[float] = None
    eps: Optional[float] = None
    bvps: Optional[float] = None
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None
    dividend_yield: Optional[float] = None
    update_time: str


class NewsRecord(BaseModel):
    id: Optional[int] = None
    code: Optional[str] = None
    title: str
    url: str
    source: Optional[str] = None
    publish_time: Optional[str] = None
    summary: Optional[str] = None
    created_at: str


# ---------- 请求/响应 ----------
class AnalyzeRequest(BaseModel):
    code: str = Field(..., description="6 位 A 股代码，如 600519")
    question: Optional[str] = Field(None, description="用户附加求，如对该股走势的看法")
    use_search: bool = Field(True, description="是否联网搜索补充实时上下文")
    top_k: Optional[int] = None


class AnalyzeResponse(BaseModel):
    code: str
    question: Optional[str] = None
    local_context: dict
    web_context: List[dict]
    analysis: str
    llm_meta: dict


class HealthResponse(BaseModel):
    status: str
    data_source: str
    storage: str
    llm_base_url: str
    search_provider: str


# ---------- 企业微信订阅管理 ----------
class SubscriptionCreate(BaseModel):
    name: str = Field(...)
    webhook_url: str = Field(...)
    webhook_secret: Optional[str] = None
    watch_codes: List[str] = Field(default_factory=list)
    enabled: bool = True


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    watch_codes: Optional[List[str]] = None
    enabled: Optional[bool] = None


class SubscriptionRecord(BaseModel):
    id: int
    name: str
    webhook_url: str
    webhook_secret: str = ""
    watch_codes: List[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: str


class PushResult(BaseModel):
    subscription_id: int
    name: Optional[str] = None
    status: str
    reason: Optional[str] = None


class PushAnalyzeRequest(BaseModel):
    code: str = Field(..., description="6 位 A 股代码，如 600519")
    question: Optional[str] = None
    use_search: bool = True
    top_k: Optional[int] = None
