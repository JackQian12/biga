# -*- coding: utf-8 -*-
"""市场信息快报生成器：行情数据 + 市场新闻 一体的 Markdown 快报。

数据来源（akshare 免费接口，无需 token）：
- 指数实时：stock_zh_index_spot_sina（替代已下线的 stock_zh_index_spot）
- 全A实时：stock_zh_a_spot（用于涨幅榜/成交额榜）
- 市场新闻：多渠道快讯（财联社/同花顺/富途/央视/财新/新浪）
- 板块热度：stock_sector_spot（新浪行业板块）

生成到 config.storage 目录下的「市场信息快报.md」。
根目录入口：python gen_report.py
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import get_config

logger = logging.getLogger(__name__)

INDEX_WATCH = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sh000300", "沪深300"),
    ("sz399006", "创业板指"),
    ("sh000016", "上证50"),
    ("sh000905", "中证500"),
]

# 渠道由 news_channels.CHANNELS 统一管理，report 仅复用 fetch_flash_news()


def _num(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _safe_pct(r: Dict[str, Any]) -> Optional[float]:
    try:
        return float(r.get("涨跌幅"))
    except Exception:
        return None


def _safe_amount(r: Dict[str, Any]) -> Optional[float]:
    try:
        return float(r.get("成交额"))
    except Exception:
        return None


def _fetch_index_rows() -> List[Dict[str, Any]]:
    """拉取指数实时，返回 INDEX_WATCH 对应的行。"""
    import akshare as ak

    df = ak.stock_zh_index_spot_sina()
    if df is None or df.empty:
        return []
    by_code = {str(r["代码"]): r for r in df.to_dict("records")}
    out = []
    for c, name in INDEX_WATCH:
        r = by_code.get(c)
        if r:
            row = dict(r)
            if not str(row.get("名称") or "").strip():
                row["名称"] = name
            out.append(row)
    return out


def _fetch_a_spot() -> List[Dict[str, Any]]:
    """全A实时行情，用于涨幅榜/成交额榜。"""
    import akshare as ak

    df = ak.stock_zh_a_spot()
    if df is None or df.empty:
        return []
    return df.to_dict("records")


def _fetched_flash_news(limit_per_channel: int = 30, cx_limit: int = 8) -> List[Dict[str, Any]]:
    """实时从各新闻渠道抓取并规范化，返回按时间倒序的新闻列表。

    渠道列表/去重/规范化统一由 news_channels.fetch_flash_news() 提供，
    此处仅做按时间倒序排序，避免重复维护，后续扩源只改 news_channels。
    cx_limit 用于削减财新占比：财新新闻多为周刊/宏观测内容、鲜含 A 股简称，
    限制其条数可让其他渠道（财联社/同花顺/新浪等）更多进入快讯、提升关联个股概率。
    """
    import app.services.news_channels as nc
    from ..config import get_config

    items = nc.fetch_flash_news(get_config().news, limit_per_channel=limit_per_channel)
    items.sort(key=lambda x: str(x.get("publish_time") or ""), reverse=True)
    # 削减财新占比，避免其霸占快讯；财新之外渠道不设上限
    if cx_limit is not None and cx_limit > 0:
        kept: List[Dict[str, Any]] = []
        cx_seen = 0
        for it in items:
            if str(it.get("source") or "").startswith("财新"):
                if cx_seen >= cx_limit:
                    continue
                cx_seen += 1
            kept.append(it)
        items = kept
    return items


def _build_name_to_code(a_rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """由全A实时行情构建『股票简称 -> 代码』映射，用于在新闻文本中匹配关联个股。

    同一简称可能对应多个代码时，仅保留第一个（以行序为准）。
    """
    mapping: Dict[str, str] = {}
    for r in a_rows:
        name = str(r.get("名称") or "").strip()
        code = str(r.get("代码") or "").strip()
        if name and code and name not in mapping:
            mapping[name] = code
    return mapping


def _match_related(text: str, name_to_code: Dict[str, str], max_hits: int = 6) -> List[str]:
    """在新闻文本（标题+摘要）中匹配出现的股票简称，返回『代码 名称』项列表，去重且限量。"""
    if not text or not name_to_code:
        return []
    hits: List[str] = []
    for name, code in name_to_code.items():
        # 只匹配较长（>=2 字）的简称，降低噪声
        if len(name) < 2:
            continue
        if name in text:
            line = f"{code} {name}"
            if line not in hits:
                hits.append(line)
            if len(hits) >= max_hits:
                break
    return hits


def _sort_news_by_related(items: List[Dict[str, Any]],
                          name_to_code: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """把含股票简称的快讯排在前面，其余保持原时间倒序（稳定排序）。

    便于用户在快讯区优先看到与 A 股个股关联的内容；不删除任何新闻。
    """
    def _hit(it: Dict[str, Any]) -> bool:
        text = f"{it.get('title') or ''} {it.get('summary') or ''}"
        return bool(_match_related(text, name_to_code or {}))
    return sorted(items, key=lambda it: 0 if _hit(it) else 1)


def _fmt_news_md(items: List[Dict[str, Any]], limit: int = 25,
                 name_to_code: Optional[Dict[str, str]] = None) -> List[str]:
    lines: List[str] = []
    for it in items[:limit]:
        title = str(it.get("title") or "").replace("|", "\\|").strip()
        src = str(it.get("source") or "").replace("|", "\\|")
        pt = str(it.get("publish_time") or "")
        url = str(it.get("url") or "").strip()
        if url:
            lines.append(f"- **[{title}]({url})** `{src}` {pt}")
        else:
            lines.append(f"- **{title}** `{src}` {pt}")
        # 关联个股：在标题+摘要中匹配股票简称，追加在新闻后面
        text = f"{it.get('title') or ''} {it.get('summary') or ''}"
        related = _match_related(text, name_to_code or {})
        if related:
            lines.append("    > 📌 关联个股：" + "，".join(related))
    return lines


def generate_report(out_path: Optional[Path] = None) -> str:
    """拉取实时行情 + 市场新闻，生成 Markdown 快报并写入文件。"""
    cfg = get_config()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_hm = now.strftime("%H:%M")
    if out_path is None:
        # 文件名带日期时间，避免每次覆盖旧快报
        out_path = cfg.db_path.parent / now.strftime("市场信息快报_%Y%m%d_%H%M%S.md")

    lines: List[str] = []
    lines.append("# 市场信息快报")
    lines.append("")
    lines.append(f"> 数据来源：akshare（实时）| 生成时间：{date_str} {time_hm}")
    lines.append("")

    # ---- 一、指数 ----
    idx_rows = _fetch_index_rows()
    lines.append("## 一、主要指数")
    lines.append("")
    if idx_rows:
        lines.append("| 代码 | 名称 | 最新价 | 涨跌额 | 涨跌幅 | 昨收 | 今开 | 最高 | 最低 | 成交额 |")
        lines.append("|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|")
        for r in idx_rows:
            lines.append(
                f"| {r.get('代码')} | {r.get('名称')} | {_num(r.get('最新价'))} | {_num(r.get('涨跌额'))} | "
                f"{_num(r.get('涨跌幅'))} | {_num(r.get('昨收'))} | {_num(r.get('今开'))} | "
                f"{_num(r.get('最高'))} | {_num(r.get('最低'))} | {_num(r.get('成交额'))} |"
            )
    else:
        lines.append("（未能获取指数数据）")
    lines.append("")

    # ---- 二、涨幅榜 ----
    a_rows = _fetch_a_spot()
    name_to_code = _build_name_to_code(a_rows)  # 用于新闻关联个股匹配
    gainers = sorted([r for r in a_rows if _safe_pct(r) is not None],
                     key=_safe_pct, reverse=True)[:10]
    lines.append("## 二、涨幅榜 Top 10")
    lines.append("")
    if gainers:
        lines.append("| 代码 | 名称 | 最新价 | 涨跌幅 | 涨跌额 | 成交量 | 成交额 |")
        lines.append("|:--|:--|--:|--:|--:|--:|--:|")
        for r in gainers:
            lines.append(
                f"| {r.get('代码')} | {r.get('名称')} | {_num(r.get('最新价'))} | {_num(r.get('涨跌幅'))} | "
                f"{_num(r.get('涨跌额'))} | {_num(r.get('成交量'))} | {_num(r.get('成交额'))} |"
            )
    else:
        lines.append("（未能获取个股行情）")
    lines.append("")

    # ---- 三、成交额榜 ----
    amount_sort = sorted([r for r in a_rows if _safe_amount(r) is not None],
                         key=_safe_amount, reverse=True)[:10]
    lines.append("## 三、成交额榜 Top 10")
    lines.append("")
    if amount_sort:
        lines.append("| 代码 | 名称 | 最新价 | 涨跌幅 | 成交量 | 成交额 |")
        lines.append("|:--|:--|--:|--:|--:|--:|")
        for r in amount_sort:
            lines.append(
                f"| {r.get('代码')} | {r.get('名称')} | {_num(r.get('最新价'))} | {_num(r.get('涨跌幅'))} | "
                f"{_num(r.get('成交量'))} | {_num(r.get('成交额'))} |"
            )
    else:
        lines.append("（未能获取个股行情）")
    lines.append("")

    # ---- 四、市场快讯 ----
    news = _fetched_flash_news()
    lines.append("## 四、市场快讯")
    lines.append("")
    if news:
        lines.append("以下快讯聚合自财联社/同花顺/富途/央视/财新/新浪，含关联个股者优先展示：")
        lines.append("")
        news = _sort_news_by_related(news, name_to_code)
        lines.extend(_fmt_news_md(news, limit=25, name_to_code=name_to_code))
    else:
        lines.append("（当前未能从渠道获取市场新闻）")
    lines.append("")

    # ---- 五、板块热度 ----
    lines.append("## 五、板块热度（涨幅居前行业）")
    lines.append("")
    try:
        import akshare as ak

        df = ak.stock_sector_spot()
        if df is not None and not df.empty:
            rows = df.to_dict("records")

            def _p(r):
                try:
                    return float(r.get("涨跌幅") or 0)
                except Exception:
                    return 0.0

            rows.sort(key=_p, reverse=True)
            lines.append("| 板块 | 涨跌幅 | 公司家数 | 总成交额 |")
            lines.append("|:--|--:|--:|--:|")
            for r in rows[:10]:
                lines.append(
                    f"| {r.get('板块')} | {_num(r.get('涨跌幅'))} | {r.get('公司家数')} | "
                    f"{_num(r.get('总成交额'))} |"
                )
        else:
            lines.append("（未能获取板块热度）")
    except Exception as exc:
        logger.warning("板块热度获取失败：%s", exc)
        lines.append("（未能获取板块热度）")
    lines.append("")

    md = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    logger.info("已生成市场信息快报：%s（%d 字符）", out_path, len(md))
    return md


if __name__ == "__main__":  # pragma: no cover
    print(generate_report())

