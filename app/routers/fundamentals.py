# -*- coding: utf-8 -*-
"""基本面查询路由。"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import verify_token
from .. import database as db
from ..models import FundamentalsRecord

router = APIRouter(prefix="/api/v1/fundamentals", tags=["fundamentals"], dependencies=[Depends(verify_token)])


def _find_by_code(items, code):
    for it in items:
        if str(it.get("code")) == str(code):
            return it
    return None


@router.get("", response_model=list[FundamentalsRecord])
def list_fundamentals():
    return db.get_fundamentals()


@router.get("/{code}", response_model=FundamentalsRecord)
def get_fundamental(code: str):
    item = _find_by_code(db.get_fundamentals([code]), code)
    if not item:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 的基本面数据")
    return item
