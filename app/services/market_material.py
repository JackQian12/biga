# -*- coding: utf-8 -*-
"""市场素材采集：板块热度榜、财经数据日历、板块资金流向等。

这些并非单条新闻，而是供投资者参考的"市场素材"，统一以
{kind, code, content, source, metrics(dict), date, created_at} 形式写入 material 表，
供 AI 解读/日报注入上下文，帮助判断板块与宏观方向。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import NewsCfg

logger = logging.getLogger(__name__)

MATERIAL_KIND_SECTOR = "sector_heat"      # 板块热度（新浪行业板块）
MATERIAL_KIND_CALENDAR = "macro_calendar"  # 财经数据日历（百度经济）
MATERIAL_KIND_FUND_FLOW = "sector_fund_flow"  # 板块资金流向


def fetch_sector_heat(limit: int = 25) -> List[Dict[str, Any]]:
    """新浪行业板块实时热度，取涨幅靠前的板块及其龙头个股。"""
    try:
        import akshare as ak
    except Exception as exc:
        logger.warning("akshare 未安装：%s", exc)
        return []
    try:
        df = ak.stock_sector_spot()
        if df is None or df.empty:
            return []
    except Exception as exc:
        logger.warning("板块热点抓取失败：%s", exc)
        return []

    rows = df.to_dict("records")
    # 按涨幅排序，取最高的板块
    def _pct(r):
        try:
            return float(r.get("涨跌幅") or 0)
        except Exception:
            return 0.0
    rows.sort(key=_pct, reverse=True)
    top = rows[:limit]

    out: List[Dict[str, Any]] = []
    for i, r in enumerate(top):
        sector = str(r.get("板块") or r.get("label") or "").strip()
        if not sector:
            continue
        content = (
            f"板块【{sector}】涨幅 {r.get('涨跌幅')}%，公司家数 {r.get('公司家数')}，"
            f"总成交额 {r.get('总成交额')}，平均价格 {r.get('平均价格')}"
        )
        metrics = {
            "change_pct": _pct(r),
            "company_count": r.get("公司家数"),
            "total_amount": r.get("总成交额"),
            "rank": i + 1,
        }
        out.append({
            "kind": MATERIAL_KIND_SECTOR,
            "code": str(r.get("股票代码") or "").strip() or sector,
            "content": content,
            "source": "新浪行业板块",
            "metrics": metrics,
            "date": datetime.now().strftime("%Y-%m-%d"),
        })
    return out


def fetch_macro_calendar(limit: int = 15) -> List[Dict[str, Any]]:
    """百度财经经济数据日历（今日及近期重要披露）。"""
    try:
        import akshare as ak
    except Exception as exc:
        logger.warning("akshare 未安装：%s", exc)
        return []
    try:
        df = ak.news_economic_baidu()
        if df is None or df.empty:
            return []
    except Exception as exc:
        logger.warning("财经日历抓取失败：%s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for r in df.to_dict("records")[:limit]:
        event = str(r.get("事件") or "").strip()
        if not event:
            continue
        content = (
            f"{r.get('日期')} {r.get('时间')} {r.get('地区')} 公布【{event}】，"
            f"公布值 {r.get('公布')}，预期 {r.get('预期')}，前值 {r.get('前值')}，"
            f"重要性 {r.get('重要性')}"
        )
        out.append({
            "kind": MATERIAL_KIND_CALENDAR,
            "code": str(r.get("重要性") or "") + "-" + str(r.get("事件") or ""),
            "content": content,
            "source": "百度财经日历",
            "metrics": {"importance": str(r.get("重要性") or "")},
            "date": str(r.get("日期") or ""),
        })
    return out


def fetch_all_material(cfg: NewsCfg | None = None) -> List[Dict[str, Any]]:
    """按配置采集全部市场素材。"""
    if cfg is None:
        from ..config import get_config
        cfg = get_config().news
    if not cfg.material:
        return []
    result: List[Dict[str, Any]] = []
    try:
        result += fetch_sector_heat(cfg.material_sector_top)
    except Exception as exc:
        logger.warning("板块素材采集失败：%s", exc)
    try:
        result += fetch_macro_calendar(cfg.material_calendar_top)
    except Exception as exc:
        logger.warning("财经日历素材采集失败：%s", exc)
    return result
