# -*- coding: utf-8 -*-
"""妖股资金溯源：从连板妖股 → 龙虎榜席位 → 机构/游资偏好，判断其资金来源是否“有迹可循”。

基于 akshare 免费接口，仅做统计与线索整理，不构成任何投资建议。
核心链路：
1. 涨停股池 stock_zt_pool_em —— 找出当日连板数 ≥2 的妖股候选；
2. 龙虎榜明细 stock_lhb_detail_em —— 匹配候选股的龙虎榜上榜记录（解读列含“X家机构买入/卖出”）；
3. 机构买卖每日统计 stock_lhb_jgmmtj_em —— 汇总候选股的机构净买卖，刻画机构痕迹。

对外暴露两个入口：
- fetch_yaogu_trace()   返回结构化分析结果（dict/DataFrame），供其他模块复用；
- format_yaogu_md()     返回可直接写进《市场信息快报》的 Markdown 文本。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 参与“妖股”筛选的最低连板数（含）
MIN_LIANBAN = 2
# 疑似妖股的连板数阈值（高于此更“妖”，用于标记加粗/优先）
HOT_LIANBAN = 3

# 龙虎榜“解读”里的机构痕迹关键词
_INST_KEYWORDS = ("机构买入", "机构卖出")


def _try(fn, *args) -> "Any":
    """带日志的容错调用，接口异常时返回 None。"""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        logger.warning("接口调用失败 %s %s: %s", getattr(fn, "__name__", "?"), args, exc)
        return None


def _recent_dates(n: int = 7) -> List[str]:
    """返回最近 n 个自然日（不含今天）的 YYYYMMDD 列表，用于向前回退找交易日。"""
    today = dt.date.today()
    out: List[str] = []
    d = today - dt.timedelta(days=1)
    while len(out) < n:
        out.append(d.strftime("%Y%m%d"))
        d -= dt.timedelta(days=1)
    return out


def _pick_latest_zt(back_days: int = 5) -> "tuple[str, Any] | None":
    """取最近可用的涨停股池数据，返回 (日期, DataFrame) 或 None。"""
    import akshare as ak

    for d in _recent_dates(back_days):
        df = _try(ak.stock_zt_pool_em, d)
        if df is not None and not df.empty:
            return d, df
    return None


def _code_str(v: Any) -> str:
    """代码统一转字符串并补零（机构统计里可能为 603893 而非 '603893'）。"""
    if v in (None, ""):
        return ""
    try:
        return str(int(float(v))).zfill(6)
    except Exception:
        return str(v)


def _fmt_amount(v: Any) -> str:
    """金额格式化为万/亿 中文（支持负数）。"""
    try:
        f = float(v)
    except Exception:
        return "-"
    sign = "-" if f < 0 else ""
    a = abs(f)
    if a >= 1e8:
        return f"{sign}{a / 1e8:.2f}亿"
    if a >= 1e4:
        return f"{sign}{a / 1e4:.2f}万"
    return f"{sign}{a:.0f}"


def fetch_yaogu_trace(top_n: int = 8, back_days: int = 7) -> Dict[str, Any]:
    """妖股资金溯源主分析，返回结构化结果。

    :return: {
        'zt_date': 涨停股池对应日期,
        'rows': [每只妖股候选的信息 dict],
        'lhb_rows': 命中的龙虎榜明细（DataFrame）,
        'jg_rows': 命中的机构买卖统计（DataFrame）,
        'error': str | None
    }
    """
    import akshare as ak

    zt = _pick_latest_zt(back_days)
    if zt is None:
        return {"zt_date": None, "rows": [], "lhb_rows": None, "jg_rows": None,
                "error": "涨停股池近几日无数据"}

    zt_date, zt_df = zt
    if "连板数" not in zt_df.columns:
        return {"zt_date": zt_date, "rows": [], "lhb_rows": None, "jg_rows": None,
                "error": "涨停股池缺少连板数字段"}

    # 1) 妖股候选：连板数 >= MIN_LIANBAN，按连板数降序、封板资金降序
    cand = zt_df[zt_df["连板数"] >= MIN_LIANBAN].sort_values(
        ["连板数", "封板资金"], ascending=False
    ).head(top_n)
    if cand.empty:
        return {"zt_date": zt_date, "rows": [], "lhb_rows": None, "jg_rows": None,
                "error": f"涨停股池中连板数 ≥ {MIN_LIANBAN} 的个股为空"}

    cand_codes = set(_code_str(c) for c in cand["代码"])
    cand_meta: Dict[str, Dict[str, Any]] = {}
    for r in cand.to_dict("records"):
        meta = {
            "代码": _code_str(r.get("代码")),
            "名称": str(r.get("名称") or ""),
            "最新价": r.get("最新价"),
            "涨跌幅": r.get("涨跌幅"),
            "连板数": int(r.get("连板数") or 0),
            "所属行业": str(r.get("所属行业") or ""),
            "封板资金": r.get("封板资金"),
            "上榜日": [],
            "解读": [],
            "龙虎榜净买额": 0.0,
            "机构净买额": 0.0,
            "买方机构数": 0,
            "卖方机构数": 0,
        }
        cand_meta[meta["代码"]] = meta

    # 2) 龙虎榜明细：匹配候选代码
    start = (dt.date.today() - dt.timedelta(days=9)).strftime("%Y%m%d")
    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
    lhb = _try(ak.stock_lhb_detail_em, start, end)
    lhb_rows = None
    if lhb is not None and not lhb.empty:
        lhb_rows = lhb[lhb["代码"].map(_code_str).isin(cand_codes)].copy()
        for r in lhb_rows.to_dict("records"):
            m = cand_meta.get(_code_str(r.get("代码")))
            if m is None:
                continue
            day = str(r.get("上榜日") or "")
            if day not in m["上榜日"]:
                m["上榜日"].append(day)
            note = str(r.get("解读") or "").strip()
            if note and note not in m["解读"]:
                m["解读"].append(note)
            try:
                m["龙虎榜净买额"] += float(r.get("龙虎榜净买额") or 0)
            except Exception:
                pass

    # 3) 机构买卖统计：匹配候选代码，汇总机构净买
    jg = _try(ak.stock_lhb_jgmmtj_em, start, end)
    jg_rows = None
    if jg is not None and not jg.empty:
        jg_rows = jg[jg["代码"].map(_code_str).isin(cand_codes)].copy()
        for r in jg_rows.to_dict("records"):
            m = cand_meta.get(_code_str(r.get("代码")))
            if m is None:
                continue
            try:
                m["机构净买额"] += float(r.get("机构买入净额") or 0)
                m["买方机构数"] += int(r.get("买方机构数") or 0)
                m["卖方机构数"] += int(r.get("卖方机构数") or 0)
            except Exception:
                pass

    # 4) 综合判断“是否有迹可循”
    for m in cand_meta.values():
        m["是否有迹"] = _judge(m)

    return {
        "zt_date": zt_date,
        "rows": [cand_meta[c] for c in cand_meta if cand_meta[c]["代码"] in cand_codes],
        "lhb_rows": lhb_rows,
        "jg_rows": jg_rows,
        "error": None,
    }


def _judge(m: Dict[str, Any]) -> str:
    """根据龙虎榜与机构统计判断妖股资金痕迹。"""
    has_lhb = bool(m["上榜日"])
    inst_seen_in_detail = any(
        k in note for note in m["解读"] for k in _INST_KEYWORDS
    )
    inst_stats = m["机构净买额"] != 0 or m["买方机构数"] > 0 or m["卖方机构数"] > 0

    if not has_lhb:
        return "未上龙虎榜（资金痕迹或集中于场内封板，无公开席位线索）"
    if inst_seen_in_detail or inst_stats:
        if m["机构净买额"] > 0:
            return "机构净买入 %s，机构资金有迹可循" % _fmt_amount(m["机构净买额"])
        if m["机构净买额"] < 0:
            return "机构净卖出 %s（有机构痕迹，但方向偏空）" % _fmt_amount(abs(m["机构净买额"]))
        return "机构在席位中现身但净额≈0（或为多空对冲/游资席位主导）"
    return "上榜但解读未标注机构（推测以游资/席位资金为主，需席位级数据进一步印证）"


def format_yaogu_md(top_n: int = 8, back_days: int = 7) -> List[str]:
    """生成《市场信息快报》第六章节（妖股资金溯源）的 Markdown 行列表。"""
    lines: List[str] = []
    lines.append("## 六、妖股资金溯源")
    lines.append("")
    lines.append("> 连板妖股资金来源是否“有迹可循”，依据东方财富涨停池 + 龙虎榜 + 机构买卖统计。仅作线索整理，非投资建议。")
    lines.append("")

    res = fetch_yaogu_trace(top_n=top_n, back_days=back_days)
    if res.get("error"):
        lines.append(f"（未能完成资金溯源分析：{res['error']}）")
        lines.append("")
        return lines

    rows: List[Dict[str, Any]] = res["rows"]
    if not rows:
        lines.append("（近期涨停池无连板妖股候选）")
        lines.append("")
        return lines

    lines.append(f"涨停池日期：`{res['zt_date']}`；共筛选出 {len(rows)} 只连板妖股（连板数≥{MIN_LIANBAN}）：")
    lines.append("")
    lines.append("| 代码 | 名称 | 连板数 | 行业 | 封板资金 | 机构净买额 | 是否有迹可循 |")
    lines.append("|:--|:--|:--:|:--|--:|--:|:--|")
    for m in sorted(rows, key=lambda x: (x["连板数"], x["封板资金"] or 0), reverse=True):
        name = m["名称"]
        if m["连板数"] >= HOT_LIANBAN:
            name = "**" + name + "**"
        lines.append(
            f"| {m['代码']} | {name} | {m['连板数']} | {m['所属行业']} | "
            f"{_fmt_amount(m['封板资金'])} | {_fmt_amount(m['机构净买额'])} | {m['是否有迹']} |"
        )
    lines.append("")

    # 龙虎榜解读明细（仅列有上榜记录的，供人工核验席位线索）
    detail: List[Dict[str, Any]] = []
    for m in rows:
        for note in m["解读"]:
            detail.append({
                "代码": m["代码"], "名称": m["名称"], "上榜日": "、".join(m["上榜日"]),
                "解读": note, "龙虎榜净买额": _fmt_amount(m["龙虎榜净买额"]),
            })
    if detail:
        lines.append("**龙虎榜席位线索（“解读”列含机构买卖标注）：**")
        lines.append("")
        lines.append("| 代码 | 名称 | 上榜日 | 龙虎榜净买额 | 解读 |")
        lines.append("|:--|:--|:--|--:|:--|")
        for d in detail:
            lines.append(f"| {d['代码']} | {d['名称']} | {d['上榜日']} | {d['龙虎榜净买额']} | {d['解读']} |")
        lines.append("")
    else:
        lines.append("_（候选妖股近期均未上龙虎榜，无席位公开线索）_")
        lines.append("")

    lines.append("> 说明：东财龙虎榜“解读”列标注机构买卖；“机构净买额”由机构买卖每日统计汇总。游资席位级数据需另接席位明细接口，此处用机构统计近似刻画痕迹。")
    lines.append("")
    return lines


if __name__ == "__main__":  # pragma: no cover
    for ln in format_yaogu_md():
        try:
            print(ln)
        except UnicodeEncodeError:
            pass

