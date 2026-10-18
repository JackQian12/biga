# -*- coding: utf-8 -*-
"""Bearer Token 认证依赖。"""
from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from .config import AppConfig, get_config


def verify_token(
    authorization: str | None = Header(None, alias="Authorization"),
    config: AppConfig = Depends(get_config),
) -> AppConfig:
    """校验 Authorization: Bearer <token>。校验失败抛出 401。"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authorization 格式应为 "Bearer <token>"',
        )
    token = parts[1]
    if not secrets.compare_digest(token, "") and token not in config.auth.api_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 token",
        )
    return config
