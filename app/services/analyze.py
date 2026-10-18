# -*- coding: utf-8 -*-
"""AI 解读服务：本地行情/基本面/新闻 + 联网搜索上下文 → 组装 prompt → 调用 LLM。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..container import get_llm, get_search, get_datasource
from .. import database as db
from ..models import AnalyzeRequest

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是一位资深、审慎的 A 股分析师。请依据提供的【本地数据】与【联网搜索上下文】"
    "对指定个股进行客观解读，以“多维度报告”的结构分节输出，帮助投资者快速、全面地"
    "掌握信息。请严格按以下小节组织回答（若某维度数据缺失，也要明确标注“暂无数据”"
    "并跳过该节）：\n"
    "1. 行情与估值：简述最新行情、估值（PE/PB/ROE 等）与多空状态。\n"
    "2. 资金动向：依据资金流向数据，说明主力/超大单/大单净流入流出情况、资金情绪。\n"
    "3. 股东与股本：说明总股本、流通股本、股东户数及其变化趋势对筹码结构的含义。\n"
    "4. 技术面：依据 MA/RSI/KDJ/MACD 等技术指标给出短期趋势与关键点位观察。\n"
    "5. 综合研判：结合最新网络资讯给出影响因素、风险点和后市关键观察点。\n"
    "6. “参考资料”小节：逐条列出你在分析中引用的新闻/资讯原始链接"
    "（即【本地数据 - 新闻】与【联网搜索上下文】中给出的 url），格式为：标题 + 链接。"
    "若某条结论引用了新闻，请务必让读者能通过该链接找到来源。\n"
    "不构成投资建议，需提示风险。回答请使用中文，结构清晰，可超出 600 字，但避免冗余。"
)


def _safe_fetch(ds, method: str, codes: List[str]) -> List[Dict[str, Any]]:
    """调用数据源的可选扩展方法，任何异常都回退为空列表，保证主流程不中断。"""
    try:
        res = getattr(ds, method)(codes)
        return res or []
    except Exception as exc:
        logger.warning("%s 调用失败：%s", method, exc)
        return []


def build_local_context(code: str, config: AppConfig | None = None) -> Dict[str, Any]:
    """取该股本地行情+基本面+新闻，并按需补充资金/股东/技术等多维度数据。"""
    quotes = _first(db.get_quotes([code]))
    fund = _first(db.get_fundamentals([code]))
    news = db.get_news(codes=[code], limit=10) or []
    material = db.get_material(limit=config.news.material_calendar_top + config.news.material_sector_top
                               if config else 30) or []

    funds_flow: List[Dict[str, Any]] = []
    shareholders: List[Dict[str, Any]] = []
    technical: List[Dict[str, Any]] = []
    if config is not None:
        try:
            ds = get_datasource(config)
            funds_flow = _safe_fetch(ds, "fetch_funds_flow", [code])
            shareholders = _safe_fetch(ds, "fetch_shareholders", [code])
            technical = _safe_fetch(ds, "fetch_technical", [code])
        except Exception as exc:
            logger.warning("扩展数据抓取失败：%s", exc)

    return {
        "quote": quotes,
        "fundamental": fund,
        "news": news,
        "material": material,
        "funds_flow": funds_flow,
        "shareholders": shareholders,
        "technical": technical,
    }


def _first(lst):
    return lst[0] if lst else {}


def _fmt_news(news: List[Dict[str, Any]]) -> str:
    if not news:
        return "（暂无本地新闻）"
    lines = []
    for n in news:
        t = n.get("title") or ""
        s = (n.get("summary") or "")[:200]
        u = n.get("url") or ""
        src = f" | 来源：{u}" if u else ""
        lines.append(f"- {t}{('：' + s) if s else ''}{src}")
    return "\n".join(lines)


def _fmt_material(items: List[Dict[str, Any]]) -> str:
    if not items:
        return "（暂无市场素材）"
    lines = []
    for m in items:
        kind = m.get("kind") or ""
        content = m.get("content") or ""
        if kind == "sector_heat":
            label = "板块热度"
        elif kind == "macro_calendar":
            label = "财经日历"
        elif kind == "sector_fund_flow":
            label = "板块资金"
        else:
            label = kind
        src = m.get("source") or ""
        lines.append(f"- [{label}] {content}（来源：{src}）")
    return "\n".join(lines)


def _fmt_number(v) -> str:
    """把数值格式化为字符串，None/空时返回“暂无”。"""
    if v is None or v == "":
        return "暂无"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _fmt_funds_flow(items: List[Dict[str, Any]]) -> str:
    """格式化资金流向数据。"""
    if not items:
        return "（暂无资金流向数据）"
    lines = []
    f = items[0]
    lines.append(f"- 主力净流入：{_fmt_number(f.get('main_net_inflow'))} 元")
    lines.append(f"- 超大单净流入：{_fmt_number(f.get('super_net_inflow'))} 元")
    lines.append(f"- 大单净流入：{_fmt_number(f.get('large_net_inflow'))} 元")
    lines.append(f"- 中单净流入：{_fmt_number(f.get('medium_net_inflow'))} 元")
    lines.append(f"- 小单净流入：{_fmt_number(f.get('small_net_inflow'))} 元")
    if f.get("date"):
        lines.append(f"- 数据日期：{f.get('date')}")
    return "\n".join(lines)


def _fmt_shareholders(items: List[Dict[str, Any]]) -> str:
    """格式化股东/股本结构数据。"""
    if not items:
        return "（暂无股东/股本数据）"
    f = items[0]
    lines = []
    if f.get("name"):
        lines.append(f"- 证券名称：{f.get('name')}")
    if f.get("total_share") is not None:
        lines.append(f"- 总股本：{_fmt_number(f.get('total_share'))} 股")
    if f.get("float_share") is not None:
        lines.append(f"- 流通股本：{_fmt_number(f.get('float_share'))} 股")
    if f.get("total_mv") is not None:
        lines.append(f"- 总市值：{_fmt_number(f.get('total_mv'))} 元")
    if f.get("float_mv") is not None:
        lines.append(f"- 流通市值：{_fmt_number(f.get('float_mv'))} 元")
    if f.get("holders") is not None:
        lines.append(f"- 股东户数：{_fmt_number(f.get('holders'))}")
    if f.get("holders_change_pct") is not None:
        lines.append(f"- 股东户数较上期变化：{_fmt_number(f.get('holders_change_pct'))}%")
    if f.get("report_date"):
        lines.append(f"- 报告期：{f.get('report_date')}")
    return "\n".join(lines)


def _fmt_technical(items: List[Dict[str, Any]]) -> str:
    """格式化技术指标数据。"""
    if not items:
        return "（暂无技术指标数据）"
    f = items[0]
    lines = []
    if f.get("turnover_rate") is not None:
        lines.append(f"- 换手率：{_fmt_number(f.get('turnover_rate'))}%")
    if f.get("volume_ratio") is not None:
        lines.append(f"- 量比：{_fmt_number(f.get('volume_ratio'))}")
    ma = [f.get(k) for k in ("ma5", "ma10", "ma20", "ma60")]
    if any(v is not None for v in ma):
        lines.append("- 均线 MA5/10/20/60："
                     f"{_fmt_number(ma[0])} / {_fmt_number(ma[1])} / {_fmt_number(ma[2])} / {_fmt_number(ma[3])}")
    rsi = [f.get(k) for k in ("rsi6", "rsi12", "rsi24")]
    if any(v is not None for v in rsi):
        lines.append(f"- RSI6/12/24：{_fmt_number(rsi[0])} / {_fmt_number(rsi[1])} / {_fmt_number(rsi[2])}")
    if f.get("kdj_k") is not None:
        lines.append(f"- KDJ：K={_fmt_number(f.get('kdj_k'))} D={_fmt_number(f.get('kdj_d'))} J={_fmt_number(f.get('kdj_j'))}")
    if f.get("macd_dif") is not None or f.get("macd_bar") is not None:
        lines.append(f"- MACD：DIF={_fmt_number(f.get('macd_dif'))} DEA={_fmt_number(f.get('macd_dea'))} 柱={_fmt_number(f.get('macd_bar'))}")
    if f.get("date"):
        lines.append(f"- 数据日期：{f.get('date')}")
    return "\n".join(lines)


def analyze(request: AnalyzeRequest, config: AppConfig) -> Dict[str, Any]:
    code = request.code
    local = build_local_context(code, config)
    question = request.question or f"请解读 {code} 的最新状况。"

    web_context: List[Dict[str, Any]] = []
    if request.use_search:
        search = get_search(config)
        query = f"{code} {local['quote'].get('name', '')} 最新消息 研报 财报"
        top_k = request.top_k or config.search.top_k
        try:
            results = search.search(query, top_k=top_k)
            web_context = [r.to_dict() for r in results]
        except Exception as exc:
            web_context = [{"error": str(exc)}]

    prompt = _build_prompt(code, local, web_context, question)
    try:
        llm = get_llm(config)
        analysis_text = llm.complete(prompt)
    except Exception as exc:
        logger.exception("LLM 调用失败")
        analysis_text = f"（LLM 调用失败：{exc}）"

    return {
        "code": code,
        "question": question,
        "local_context": local,
        "web_context": web_context,
        "analysis": analysis_text,
        "llm_meta": {
            "base_url": config.llm.base_url,
            "model": config.llm.model or "endpoint-default",
        },
    }


def _build_prompt(code, local, web_context, question) -> str:
    quote = local.get("quote") or {}
    fund = local.get("fundamental") or {}
    quote_str = (
        f"最新价 {quote.get('price')}，涨跌幅 {quote.get('change_pct')}%，"
        f"今开 {quote.get('open')}，最高 {quote.get('high')}，最低 {quote.get('low')}，"
        f"成交量 {quote.get('volume')}，成交额 {quote.get('amount')}，更新 {quote.get('update_time')}"
    )
    fund_str = (
        f"PE {fund.get('pe')}，PB {fund.get('pb')}，ROE {fund.get('roe')}%，"
        f"总市值 {fund.get('market_cap')}，EPS {fund.get('eps')}，BPS {fund.get('bvps')}，"
        f"营收同比 {fund.get('revenue_growth')}%，净利同比 {fund.get('profit_growth')}%，"
        f"股息率 {fund.get('dividend_yield')}%"
        if fund else "（暂无基本面数据）"
    )
    web_str = "\n".join(
        f"[{i}] {r.get('title','')} | {r.get('url','')}\n摘要：{r.get('snippet') or r.get('content','')[:400]}"
        for i, r in enumerate(web_context, 1)
    ) or "（未联网或搜索无结果）"

    funds_str = _fmt_funds_flow(local.get("funds_flow") or [])
    share_str = _fmt_shareholders(local.get("shareholders") or [])
    tech_str = _fmt_technical(local.get("technical") or [])

    prompt = f"""{SYSTEM_PROMPT}

【请求】{question}

【本地数据 - 行情】
{quote_str}

【本地数据 - 基本面】
{fund_str}

【本地数据 - 资金流向】
{funds_str}

【本地数据 - 股东/股本】
{share_str}

【本地数据 - 技术指标】
{tech_str}

【本地数据 - 新闻】
{_fmt_news(local.get('news') or [])}

【市场素材（板块热度/财经日历）】
{_fmt_material(local.get('material') or [])}

【联网搜索上下文】
{web_str}

请按“多维度报告”分节给出解读（行情与估值 / 资金动向 / 股东与股本 / 技术面 / 综合研判 / 参考资料）。
"""
    return prompt
