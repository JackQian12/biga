# -*- coding: utf-8 -*-
"""AI 解读路由：整合本地数据 + 联网搜索 + LLM。"""
from fastapi import APIRouter, Depends

from ..auth import verify_token
from ..config import AppConfig, get_config
from ..models import AnalyzeRequest, AnalyzeResponse
from ..services.analyze import analyze

router = APIRouter(prefix="/api/v1/analyze", tags=["analyze"], dependencies=[Depends(verify_token)])


@router.post("", response_model=AnalyzeResponse)
def do_analyze(req: AnalyzeRequest, config: AppConfig = Depends(get_config)):
    return analyze(req, config)
