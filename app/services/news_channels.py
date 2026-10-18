# -*- coding: utf-8 -*-
"""多渠道新闻聚合服务。

把多个已验证可用的资讯来源（财联社/同花顺/富途/央视/财新）统一规范化为 news 行，
写入数据库 news 表（code 为空代表全市场/热点新闻）。每个渠道独立失败不影响整体。

本模块仅依赖 akshare（延迟 import），若未安装或某渠道上游异常会在该渠道返回空。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import NewsCfg

logger = logging.getLogger(__name__)

# 每个渠道的读取/规范化函数：入参 row(dict)，出参 dict{title,url,source,publish_time,summary} 或 None
def _norm_cls(row: Dict[str, Any]) -> Dict[str, Any] | None:
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    date = str(row.get("发布日期") or "").strip()
    tm = str(row.get("发布时间") or "").strip()
    return {
        "title": title,
        "url": "",
        "source": "财联社",
        "publish_time": f"{date} {tm}".strip() or datetime.now().isoformat(timespec="seconds"),
        "summary": str(row.get("内容") or "")[:500],
    }


def _norm_ths(row: Dict[str, Any]) -> Dict[str, Any] | None:
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "url": str(row.get("链接") or "").strip(),
        "source": "同花顺",
        "publish_time": str(row.get("发布时间") or "").strip() or datetime.now().isoformat(timespec="seconds"),
        "summary": str(row.get("内容") or "")[:500],
    }


def _norm_futu(row: Dict[str, Any]) -> Dict[str, Any] | None:
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "url": str(row.get("链接") or "").strip(),
        "source": "富途",
        "publish_time": str(row.get("发布时间") or "").strip() or datetime.now().isoformat(timespec="seconds"),
        "summary": str(row.get("内容") or "")[:500],
    }


def _norm_cctv(row: Dict[str, Any]) -> Dict[str, Any] | None:
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "url": "",
        "source": "央视新闻",
        "publish_time": str(row.get("date") or "").strip() or datetime.now().isoformat(timespec="seconds"),
        "summary": str(row.get("content") or "")[:500],
    }


def _norm_cx(row: Dict[str, Any]) -> Dict[str, Any] | None:
    summary = str(row.get("summary") or "").strip()
    if not summary:
        return None
    tags = str(row.get("tag") or "").strip()
    title = summary.splitlines()[0][:60] if summary else f"财新快讯：{tags}"
    return {
        "title": title,
        "url": str(row.get("url") or "").strip(),
        "source": f"财新[{tags}]" if tags else "财新",
        "publish_time": datetime.now().isoformat(timespec="seconds"),
        "summary": summary[:500],
    }


def _norm_sina(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """新浪全球财经快讯（stock_info_global_sina）列：时间/内容。"""
    content = str(row.get("内容") or "").strip()
    if not content:
        return None
    title = content.splitlines()[0][:60].strip()
    tm = str(row.get("时间") or "").strip()
    return {
        "title": title,
        "url": "",
        "source": "新浪快讯",
        "publish_time": tm or datetime.now().isoformat(timespec="seconds"),
        "summary": content[:500],
    }


# 名称 -> (akshare 函数名, 规范化函数, 前端展示名)
CHANNELS = {
    "cls": ("stock_info_global_cls", _norm_cls, "财联社电报"),
    "ths": ("stock_info_global_ths", _norm_ths, "同花顺快讯"),
    "futu": ("stock_info_global_futu", _norm_futu, "富途快讯"),
    "cctv": ("news_cctv", _norm_cctv, "央视新闻"),
    "cx": ("stock_news_main_cx", _norm_cx, "财新快讯"),
    "sina": ("stock_info_global_sina", _norm_sina, "新浪全球快讯"),
}


def fetch_flash_news(cfg: NewsCfg | None = None,
                     limit_per_channel: int | None = None) -> List[Dict[str, Any]]:
    """按配置依次拉取各启用的新闻渠道，去重后返回规范化结果。"""
    if cfg is None:
        from ..config import get_config
        cfg = get_config().news
    enabled = cfg.channels or list(CHANNELS.keys())
    limit = limit_per_channel or cfg.limit_per_channel
    try:
        import akshare as ak
    except Exception as exc:
        logger.warning("akshare 未安装，无法聚合新闻渠道：%s", exc)
        return []

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for name in enabled:
        if name not in CHANNELS:
            logger.warning("未知新闻渠道：%s，跳过", name)
            continue
        fn_name, norm, _ = CHANNELS[name]
        try:
            df = getattr(ak, fn_name)()
            rows = df.to_dict("records") if df is not None and not df.empty else []
        except Exception as exc:
            logger.warning("渠道[%s]抓取失败：%s", name, exc)
            continue
        added = 0
        for r in rows:
            try:
                item = norm(r)
            except Exception:
                item = None
            if not item:
                continue
            key = (item["title"], item["source"])
            if key in seen:
                continue
            seen.add(key)
            item["code"] = None
            out.append(item)
            added += 1
            if added >= limit:
                break
    return out
