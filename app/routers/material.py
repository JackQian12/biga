# -*- coding: utf-8 -*-
"""市场素材查询路由。"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..auth import verify_token
from .. import database as db

router = APIRouter(prefix="/api/v1/material", tags=["material"], dependencies=[Depends(verify_token)])


@router.get("")
def list_material(kind: Optional[str] = Query(None), limit: int = Query(50, le=200)):
    return db.get_material(kind=kind, limit=limit)
