# -*- coding: utf-8 -*-
"""行情查询路由。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import verify_token
from ..config import AppConfig
from .. import database as db
from ..models import QuoteRecord

router = APIRouter(prefix="/api/v1/quotes", tags=["quotes"], dependencies=[Depends(verify_token)])


def _find_by_code(items, code):
    for it in items:
        if str(it.get("code")) == str(code):
            return it
    return None


@router.get("", response_model=List[QuoteRecord])
def list_quotes():
    return db.get_quotes()


@router.get("/{code}", response_model=QuoteRecord)
def get_quote(code: str):
    item = _find_by_code(db.get_quotes([code]), code)
    if not item:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的行情数据")
    return item
