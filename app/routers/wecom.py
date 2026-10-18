# -*- coding: utf-8 -*-
"""企业微信订阅管理路由 + 手动触发推送。"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_token
from .. import database as db
from ..config import AppConfig, get_config
from ..models import (
    PushAnalyzeRequest, PushResult, SubscriptionCreate, SubscriptionRecord,
    SubscriptionUpdate,
)
from ..services.push import push_all, push_analysis, push_to_subscription

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/subscriptions",
    tags=["wecom"],
    dependencies=[Depends(verify_token)],
)


@router.get("", response_model=List[SubscriptionRecord])
def list_subscriptions():
    return db.get_subscriptions()


@router.post("", response_model=SubscriptionRecord, status_code=201)
def create_subscription(payload: SubscriptionCreate):
    sid = db.add_subscription(
        name=payload.name,
        webhook_url=payload.webhook_url,
        watch_codes=payload.watch_codes,
        webhook_secret=payload.webhook_secret or "",
        enabled=payload.enabled,
    )
    return db.get_subscription(sid)


@router.get("/{sid}", response_model=SubscriptionRecord)
def get_subscription(sid: int):
    sub = db.get_subscription(sid)
    if not sub:
        raise HTTPException(status_code=404, detail=f"订阅 {sid} 不存在")
    return sub


@router.patch("/{sid}", response_model=SubscriptionRecord)
def update_subscription(sid: int, payload: SubscriptionUpdate):
    n = db.update_subscription(
        sid,
        name=payload.name,
        webhook_url=payload.webhook_url,
        webhook_secret=payload.webhook_secret,
        watch_codes=payload.watch_codes,
        enabled=payload.enabled,
    )
    if not n:
        raise HTTPException(status_code=404, detail=f"订阅 {sid} 不存在")
    return db.get_subscription(sid)


@router.delete("/{sid}", response_model=dict)
def delete_subscription(sid: int):
    n = db.delete_subscription(sid)
    if not n:
        raise HTTPException(status_code=404, detail=f"订阅 {sid} 不存在")
    return {"deleted": sid}


@router.post("/{sid}/push", response_model=PushResult)
def push_one(sid: int, config: AppConfig = Depends(get_config)):
    sub = db.get_subscription(sid)
    if not sub:
        raise HTTPException(status_code=404, detail=f"订阅 {sid} 不存在")
    try:
        return push_to_subscription(config, sub)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc


@router.post("/{sid}/push-analyze", response_model=PushResult)
def push_one_analyze(sid: int, payload: PushAnalyzeRequest,
                     config: AppConfig = Depends(get_config)):
    """对单只股票跑一遍融合 LLM+联网搜索的解读，再推送给该订阅分组。"""
    sub = db.get_subscription(sid)
    if not sub:
        raise HTTPException(status_code=404, detail=f"订阅 {sid} 不存在")
    try:
        return push_analysis(
            config, sub,
            code=payload.code,
            question=payload.question,
            use_search=payload.use_search,
            top_k=payload.top_k,
        )
    except Exception as exc:
        logger.exception("向订阅 %s 推送个股解读失败", sid)
        raise HTTPException(status_code=502, detail=f"推送失败：{exc}") from exc


@router.post("/push-all", response_model=List[PushResult])
def push_everything(config: AppConfig = Depends(get_config)):
    try:
        return push_all(config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"推送失败：{exc}") from exc
