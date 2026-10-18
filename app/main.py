# -*- coding: utf-8 -*-
"""FastAPI 应用工厂：路由注册、调度启动、健康检查。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from .auth import verify_token
from .config import AppConfig, get_config
from .container import get_datasource, get_llm, get_search
from .models import HealthResponse
from .scheduler import AppScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: AppScheduler | None = None


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _scheduler
        # 提前触发一次数据源可用性检查（不实际拉取全量数据，避免启动卡住）
        datasource = get_datasource(config)
        logger.info("数据源: %s -> %s", config.data_source.provider, datasource.check_available())
        logger.info("LLM 端点: %s", config.llm.base_url)
        logger.info("搜索: %s (engine=%s)", get_search(config).name, config.search.engine)

        if config.schedule:
            _scheduler = AppScheduler(config)
            _scheduler.start()
        yield
        if _scheduler:
            _scheduler.shutdown()

    app = FastAPI(title="A-Share Info Collector", version="1.0.0", lifespan=lifespan)

    from .routers import analyze, fundamentals, material, news, quotes, wecom
    app.include_router(quotes.router)
    app.include_router(fundamentals.router)
    app.include_router(material.router)
    app.include_router(news.router)
    app.include_router(analyze.router)
    app.include_router(wecom.router)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health(config: AppConfig = Depends(get_config)):
        ds = get_datasource(config)
        return HealthResponse(
            status="ok",
            data_source=f"{ds.name} ({ds.check_available()})",
            storage=str(config.db_path),
            llm_base_url=config.llm.base_url,
            search_provider=get_search(config).name,
        )

    @app.get("/", tags=["system"])
    def root():
        return {"msg": "A-Share Info Collector API. 访问 /docs 查看接口文档。"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
