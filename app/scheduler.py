# -*- coding: utf-8 -*-
"""APScheduler 调度：盘中定时同步行情/基本面，定时抓取新闻。"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from .config import AppConfig, get_config
from .container import get_datasource
from . import database as db

logger = logging.getLogger(__name__)


def push_daily(config: Optional[AppConfig] = None) -> dict:
    """定时把 AI 日报推送到所有启用的企业微信订阅分组。"""
    cfg = config or get_config()
    if not cfg.wecom.enabled:
        return {"status": "disabled", "reason": "wecom.enabled=False"}
    subs = db.get_subscriptions(enabled_only=True)
    if not subs:
        return {"status": "no-subscriptions", "reason": "无订阅分组"}
    from .services.push import push_all
    results = push_all(cfg)
    errors = [r for r in results if r.get("status") in ("error", "disabled", "empty")]
    return {"status": "ok" if not errors else "partial", "results": results}


def _is_trading_weekday(dt: Optional[datetime] = None) -> bool:
    dt = dt or datetime.now()
    return dt.weekday() < 5


def _is_trading_time(dt: Optional[datetime] = None) -> bool:
    dt = dt or datetime.now()
    if not _is_trading_weekday(dt):
        return False
    seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
    return 9 * 3600 + 30 * 60 <= seconds <= 15 * 3600


def sync_market(config: Optional[AppConfig] = None) -> dict:
    """同步全市场行情+基本面到本地库。返回统计。"""
    cfg = config or get_config()
    if cfg.schedule.update_market_only_in_trading and not _is_trading_time():
        return {"status": "skipped", "reason": "非交易时段"}
    ds = get_datasource(cfg)
    avail = ds.check_available()
    if avail != "ok":
        return {"status": "error", "reason": avail}

    quotes = ds.fetch_quotes()
    q_n = db.upsert_quotes(quotes)
    try:
        fund = ds.fetch_fundamentals()
        f_n = db.upsert_fundamentals(fund)
    except Exception as exc:
        logger.exception("基本面同步失败")
        f_n = 0
    return {"status": "ok", "quotes": q_n, "fundamentals": f_n}


def sync_news(config: Optional[AppConfig] = None) -> dict:
    """从多渠道聚合热点新闻入库（财联社/同花顺/富途/央视/财新）+ 联网搜索补充。"""
    from .services.news_channels import fetch_flash_news
    cfg = config or get_config()

    # 渠道 1：akshare 快讯通道聚合
    rows = fetch_flash_news(cfg.news)
    n = db.insert_news(rows)

    # 渠道 2：联网搜索补充热点
    try:
        from .container import get_search
        search = get_search(cfg)
        web_rows = []
        for q in ("A股 今日 市场 热点 新闻", "宏观经济 政策 今日 A股", "涨停 连板 题材 最新"):
            try:
                results = search.search(q, top_k=min(cfg.search.top_k, 5))
            except Exception as exc:
                logger.warning("搜索 %s 失败：%s", q, exc)
                continue
            for r in results:
                web_rows.append({
                    "code": None,
                    "title": r.title,
                    "url": r.url,
                    "source": "web",
                    "publish_time": datetime.now().isoformat(timespec="seconds"),
                    "summary": (r.snippet or r.content or "")[:500],
                })
        n2 = db.insert_news(web_rows)
    except Exception as exc:
        logger.warning("联网搜索新闻补充失败：%s", exc)
        n2 = 0
    return {"status": "ok", "news": n, "web_news": n2}


def sync_material(config: Optional[AppConfig] = None) -> dict:
    """采集市场素材（板块热度/财经日历）入库。每个 kind 先清空再写入，避免堆积。"""
    from .services.market_material import fetch_all_material
    cfg = config or get_config()
    if not cfg.news.material:
        return {"status": "disabled", "reason": "news.material=False"}
    rows = fetch_all_material(cfg.news)
    if not rows:
        return {"status": "ok", "material": 0}
    kinds = {r.get("kind") for r in rows}
    for k in kinds:
        db.clear_material(k)
    n = db.insert_material(rows)
    return {"status": "ok", "material": n, "kinds": sorted(kinds)}


class AppScheduler:
    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        cfg = self.config.schedule
        self.scheduler.add_job(
            sync_market,
            trigger=IntervalTrigger(seconds=cfg.market_sync_interval_seconds),
            id="sync_market",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        self.scheduler.add_job(
            sync_news,
            trigger=IntervalTrigger(seconds=cfg.news_interval_seconds),
            id="sync_news",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=80,
        )
        self.scheduler.add_job(
            sync_material,
            trigger=IntervalTrigger(seconds=cfg.news_interval_seconds),
            id="sync_material",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=80,
        )
        # 交易日开盘前抓一次新闻
        self.scheduler.add_job(
            sync_news,
            trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=15),
            id="sync_news_morning",
            replace_existing=True,
            coalesce=True,
        )
        # 企业微信日报定时推送（读取 wecom.daily_push_time）
        if hourly := self._parse_hhmm(self.config.wecom.daily_push_time):
            self.scheduler.add_job(
                push_daily,
                trigger=CronTrigger(day_of_week="mon-fri", hour=hourly[0], minute=hourly[1]),
                id="push_daily_brief",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=180,
            )
            logger.info("日报调度已添加：每日交易日 %s", self.config.wecom.daily_push_time)
        self.scheduler.start()
        logger.info("调度器已启动")

    @staticmethod
    def _parse_hhmm(value: str):
        try:
            h, m = value.strip().split(":")
            return int(h), int(m)
        except Exception:
            return None

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
