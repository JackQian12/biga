# -*- coding: utf-8 -*-
"""盘面情报推送服务（企业微信群机器人）。

职责：把订阅分组自选股的本地行情/基本面 + 联网搜索上下文，交给 LLM 生成简明的
「A股情报日报」，再以 markdown 推送到企业微信群。支持手动触发与定时调度。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .. import database as db
from ..config import AppConfig
from ..container import get_llm, get_search
from ..notify.wecom import WecomNotifier

logger = logging.getLogger(__name__)

_BRIEFING_SYSTEM = (
    "你是一名 A 股情报编辑。请把给定的一批自选股实时行情、基本面与最新网络资讯，"
    "整理成一份面向普通投资者、结构与要点清晰的日报（中文，markdown 格式允许 `**` 与"
    " `<font color=\"info\">` 高亮）。先给总体市场与多点观察，再逐股给出 1-2 句要点与风险提示。"
    "不构成投资建议，末尾固定提示风险。控制在 800 字以内。"
)


def build_briefing(config: AppConfig, codes: List[str]) -> Dict[str, Any]:
    """组装一份日报所需数据，调用 LLM 生成 markdown 正文。"""
    codes = [c for c in codes if c]
    quotes = {q["code"]: q for q in db.get_quotes(codes)}
    funds = {f["code"]: f for f in db.get_fundamentals(codes)}
    material = db.get_material(limit=config.news.material_sector_top + config.news.material_calendar_top) or []
    material_lines = [
        f"[{m.get('source')}] {m.get('content')}" for m in material
    ]
    search = get_search(config)

    # 联网搜索各股/市场热点（限制数量避免请求过多）
    web_lines: List[str] = []
    for code in codes[: max(1, config.search.top_k)]:
        q = quotes.get(code, {})
        query = f"{code} {q.get('name','')} 最新消息 研报 财报"
        try:
            for r in search.search(query, top_k=3):
                s = (r.snippet or r.content or "")[:160]
                web_lines.append(f"[{code}] {r.title} | {s} | {r.url}")
        except Exception as exc:
            logger.warning("搜索 %s 失败：%s", code, exc)

    market_lines: List[str] = []
    for code in codes:
        q = quotes.get(code) or {}
        f = funds.get(code) or {}
        market_lines.append(
            f"{code} {q.get('name','')}：现价 {q.get('price')}，涨跌幅 {q.get('change_pct')}%，"
            f"成交额 {q.get('amount')}，PE {f.get('pe')}，PB {f.get('pb')}"
        )

    prompt = (
        f"{_BRIEFING_SYSTEM}\n\n"
        f"【自选股实时行情】\n{chr(10).join(market_lines) or '（无本地行情）'}\n\n"
        f"【联网最新资讯】\n{chr(10).join(web_lines) or '（无联网资讯）'}\n\n"
        f"【市场素材（板块热度/财经日历）】\n{chr(10).join(material_lines) or '（无市场素材）'}\n\n"
        "请据此生成日报。"
    )
    try:
        text = get_llm(config).complete(prompt)
    except Exception as exc:
        logger.exception("生成日报时 LLM 调用失败")
        text = f"（LLM 生成日报失败：{exc}）\n\n{chr(10).join(market_lines)}"

    return {"codes": codes, "markdown": text, "web_lines": len(web_lines)}


def push_to_subscription(config: AppConfig, sub: Dict[str, Any]) -> Dict[str, Any]:
    """向单个订阅分组推送。sub 来自 db.get_subscriptions()。"""
    codes = sub.get("watch_codes") or []
    if not codes:
        return {"subscription_id": sub["id"], "status": "empty", "reason": "无自选股"}
    brief = build_briefing(config, codes)
    # 未单独配置 webhook 则使用全局配置；仍无则尝试应用消息渠道
    has_webhook = bool(sub.get("webhook_url") or config.wecom.webhook_url)
    has_app = bool(config.wecom.corpid and config.wecom.agentid and config.wecom.app_secret)
    if not (has_webhook or has_app):
        return {"subscription_id": sub["id"], "status": "disabled", "reason": "未配置 webhook 或应用凭据"}
    from ..config import WecomCfg
    cfg_webhook = sub.get("webhook_url") or config.wecom.webhook_url
    per_cfg = WecomCfg(
        enabled=True,
        webhook_url=cfg_webhook,
        webhook_secret=sub.get("webhook_secret") or config.wecom.webhook_secret,
        corpid=config.wecom.corpid,
        agentid=config.wecom.agentid,
        app_secret=config.wecom.app_secret,
        app_touser=config.wecom.app_touser,
    )
    n = WecomNotifier(per_cfg)
    header = f"### 📈 A股情报日报（自选股 {len(codes)} 只）"
    content = f"{header}\n\n{brief['markdown']}"
    resp = n.send_markdown(content)
    return {"subscription_id": sub["id"], "name": sub.get("name"), "status": "ok", **resp}


def push_analysis(config: AppConfig, sub: Dict[str, Any], *, code: str,
                  question: str = None, use_search: bool = True,
                  top_k: int = None) -> Dict[str, Any]:
    """针对单只股票跑一次 /analyze 流程，把融合了 LLM+联网搜索的解读推送到订阅分组。"""
    from ..models import AnalyzeRequest
    from ..services.analyze import analyze

    req = AnalyzeRequest(code=code, question=question, use_search=use_search, top_k=top_k)
    result = analyze(req, config)
    analysis_text = result.get("analysis") or "（无解读）"

    has_webhook = bool(sub.get("webhook_url") or config.wecom.webhook_url)
    has_app = bool(config.wecom.corpid and config.wecom.agentid and config.wecom.app_secret)
    if not (has_webhook or has_app):
        return {"subscription_id": sub["id"], "status": "disabled", "reason": "未配置 webhook 或应用凭据",
                "analysis_ok": True}

    from ..config import WecomCfg
    cfg_webhook = sub.get("webhook_url") or config.wecom.webhook_url
    per_cfg = WecomCfg(
        enabled=True,
        webhook_url=cfg_webhook,
        webhook_secret=sub.get("webhook_secret") or config.wecom.webhook_secret,
        corpid=config.wecom.corpid,
        agentid=config.wecom.agentid,
        app_secret=config.wecom.app_secret,
        app_touser=config.wecom.app_touser,
    )
    name = sub.get("name") or ""
    header = f"### 🔍 个股解读 {code}"
    if name:
        header = f"### 🔍 个股解读 {code}（{name}）"
    content = f"{header}\n\n{analysis_text}"
    resp = WecomNotifier(per_cfg).send_markdown(content)
    return {"subscription_id": sub["id"], "name": sub.get("name"), "status": "ok", **resp}


def push_all(config: AppConfig) -> List[Dict[str, Any]]:
    """向所有启用的订阅分组推送日报。返回每个分组的结果。"""
    subs = db.get_subscriptions(enabled_only=True)
    if not subs:
        return []
    out = []
    for sub in subs:
        try:
            out.append(push_to_subscription(config, sub))
        except Exception as exc:
            logger.exception("推送订阅 %s 失败", sub.get("id"))
            out.append({"subscription_id": sub.get("id"), "name": sub.get("name"),
                        "status": "error", "reason": str(exc)})
    logger.info("日报推送完成，共 %s 个分组", len(out))
    return out
