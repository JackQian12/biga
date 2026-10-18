# -*- coding: utf-8 -*-
"""新闻查询路由。"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import verify_token
from .. import database as db
from ..models import NewsRecord

router = APIRouter(prefix="/api/v1/news", tags=["news"], dependencies=[Depends(verify_token)])


@router.get("", response_model=list[NewsRecord])
def list_news(code: Optional[str] = Query(None), limit: int = Query(50, le=200)):
    return db.get_news(codes=[code] if code else None, limit=limit)
