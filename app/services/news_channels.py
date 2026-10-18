# -*- coding: utf-8 -*-
"""多渠道新闻聚合服务。

把多个已验证可用的资讯来源（财联社/同花顺/富途/央视/财新/新浪/东方财富/
新华网/巨潮资讯网）统一规范化为 news 行，写入数据库 news 表
（code 为空代表全市场/热点新闻）。每个渠道独立失败不影响整体。

本模块依赖 akshare（延迟 import）与 requests/beautifulsoup4（延迟 import），
未安装或某渠道上游异常会在该渠道返回空。
新华网与巨潮资讯网为自定义 HTTP 爬虫（非 akshare）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List

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


def _norm_em(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """东方财富全球财经快讯（stock_info_global_em）列：标题/摘要/发布时间/链接。"""
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "url": str(row.get("链接") or "").strip(),
        "source": "东方财富",
        "publish_time": str(row.get("发布时间") or "").strip()
                         or datetime.now().isoformat(timespec="seconds"),
        "summary": str(row.get("摘要") or "")[:500],
    }


def _fetch_xinhua(max_items: int = 30) -> List[Dict[str, Any]]:
    """新华网-财经板块直接抓取（无公开 RSS/JSON，解析 HTML + Referer 绕过 WAF）。"""
    url = "https://www.news.cn/fortune/index.htm"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"),
        "Referer": "https://www.news.cn/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        import requests
        from bs4 import BeautifulSoup
    except Exception as exc:
        logger.warning("新华网渠道缺少 requests/beautifulsoup4：%s", exc)
        return []
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("新华网渠道抓取失败：%s", exc)
        return []
    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("新华网渠道解析失败：%s", exc)
        return []

    seen: set = set()
    rows: List[Dict[str, Any]] = []
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        href = str(a.get("href") or "").strip()
        if not title or len(title) < 6:
            continue
        if not re.search(r"/fortune/20\d{6}/[0-9a-f]{32}/c\.html$", href):
            continue
        if title in seen:
            continue
        seen.add(title)
        if href.startswith("/"):
            href = "https://www.news.cn" + href
        m = re.search(r"/fortune/(\d{4})(\d{2})(\d{2})/", href)
        pub = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
        rows.append({"标题": title, "链接": href, "发布时间": pub})
        if len(rows) >= max_items:
            break
    return rows


def _norm_xinhua(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """新华网财经新闻规范化（标题/链接路径日期）。"""
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "url": str(row.get("链接") or "").strip(),
        "source": "新华网",
        "publish_time": str(row.get("发布时间") or "").strip()
                       or datetime.now().isoformat(timespec="seconds"),
        "summary": title[:120],
    }


def _fetch_cninfo(max_items: int = 30, days: int = 1) -> List[Dict[str, Any]]:
    """巨潮资讯网（cninfo）上市公司公告抓取（官方公告接口 POST 查询 JSON）。"""
    from datetime import timedelta

    today = datetime.now()
    begin = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    import requests

    payload = {
        "pageNum": "1",
        "pageSize": str(max_items),
        "column": "sse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": f"{begin}~{end}",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://www.cninfo.com.cn/",
        "Origin": "https://www.cninfo.com.cn",
    }
    api = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    try:
        resp = requests.post(api, data=payload, headers=headers, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("巨潮资讯网渠道抓取失败：%s", exc)
        return []
    try:
        j = resp.json()
    except Exception as exc:
        logger.warning("巨潮资讯网渠道响应异常：%s", exc)
        return []

    rows: List[Dict[str, Any]] = []
    for it in (j or {}).get("announcements") or []:
        title = str(it.get("announcementTitle") or "").strip()
        if not title:
            continue
        sec_code = str(it.get("secCode") or "").strip()
        sec_name = str(it.get("secName") or "").strip()
        ts = it.get("announcementTime")
        publish = ""
        if ts:
            try:
                publish = datetime.fromtimestamp(int(ts) / 1000).isoformat(timespec="seconds")
            except Exception:
                publish = ""
        rel = str(it.get("adjunctUrl") or "").strip()
        url = f"https://static.cninfo.com.cn/{rel}" if rel else "https://www.cninfo.com.cn/new/"
        rows.append({
            "标题": title,
            "发布时间": publish,
            "证券代码": sec_code,
            "证券名称": sec_name,
            "链接": url,
        })
        if len(rows) >= max_items:
            break
    return rows


def _norm_cninfo(row: Dict[str, Any]) -> Dict[str, Any] | None:
    """巨潮资讯网公告规范化——带上证券代码/名称便于关联个股。"""
    title = str(row.get("标题") or "").strip()
    if not title:
        return None
    sec = "".join(x for x in [row.get("证券名称"), row.get("证券代码")] if x)
    return {
        "title": title,
        "url": str(row.get("链接") or "").strip(),
        "source": f"巨潮资讯网[{sec}]" if sec else "巨潮资讯网",
        "publish_time": str(row.get("发布时间") or "").strip()
                        or datetime.now().isoformat(timespec="seconds"),
        "summary": title[:120],
    }


# 名称 -> (抓取函数或 akshare 函数名, 规范化函数, 前端展示名)
CHANNELS = {
    "cls": ("stock_info_global_cls", _norm_cls, "财联社电报"),
    "ths": ("stock_info_global_ths", _norm_ths, "同花顺快讯"),
    "futu": ("stock_info_global_futu", _norm_futu, "富途快讯"),
    "cctv": ("news_cctv", _norm_cctv, "央视新闻"),
    "cx": ("stock_news_main_cx", _norm_cx, "财新快讯"),
    "sina": ("stock_info_global_sina", _norm_sina, "新浪全球快讯"),
    "em": ("stock_info_global_em", _norm_em, "东方财富快讯"),
    "xh": (_fetch_xinhua, _norm_xinhua, "新华网财经"),
    "cninfo": (_fetch_cninfo, _norm_cninfo, "巨潮资讯公告"),
}


def fetch_flash_news(cfg: NewsCfg | None = None,
                     limit_per_channel: int | None = None) -> List[Dict[str, Any]]:
    """当传入的 channels 列表为空时，回退到全部渠道；否则按传入为准。akshare 未安装时，
自定义爬虫渠道（新华网/巨潮）仍可工作，akshare 渠道会被跳过。"""
    if cfg is None:
        from ..config import get_config
        cfg = get_config().news
    enabled = cfg.channels or list(CHANNELS.keys())
    limit = limit_per_channel or cfg.limit_per_channel

    def _akshare():
        try:
            import akshare as ak
            return ak
        except Exception as exc:
            logger.warning("akshare 未安装，无法聚合 akshare 渠道：%s", exc)
            return None

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for name in enabled:
        if name not in CHANNELS:
            logger.warning("未知新闻渠道：%s，跳过", name)
            continue
        fn, norm, _ = CHANNELS[name]
        if callable(fn):          # 自定义爬虫渠道（已返回原始行 dict 列表）
            try:
                rows = fn()
            except Exception as exc:
                logger.warning("渠道[%s]抓取失败：%s", name, exc)
                continue
        else:                     # akshare 函数名字符串渠道
            ak = _akshare()
            if ak is None:
                continue
            try:
                df = getattr(ak, fn)()
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
