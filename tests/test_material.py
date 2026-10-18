# -*- coding: utf-8 -*-
"""material 表 CRUD 与多渠道新闻规范化单元测试（不联网）。"""
import pytest

import app.database as db
from app.services import news_channels as nc
from app.services.market_material import MATERIAL_KIND_CALENDAR, MATERIAL_KIND_SECTOR


def test_material_crud(app_config):
    rows = [
        {"kind": "sector_heat", "code": "601", "content": "板块【计算机】涨幅2%",
         "source": "新浪行业板块", "metrics": {"change_pct": 2.0}, "date": "2026-10-17"},
        {"kind": "macro_calendar", "code": "3-GDP", "content": "公布GDP，前值4.5",
         "source": "百度财经日历", "metrics": {"importance": "3"}, "date": "2026-10-18"},
    ]
    assert db.insert_material(rows) == 2
    got = db.get_material()
    assert len(got) == 2
    by_kind = {m["kind"]: m for m in got}
    assert by_kind["sector_heat"]["metrics"]["change_pct"] == 2.0  # metrics JSON 反序列化
    # 按 kind 过滤
    assert len(db.get_material(kind=MATERIAL_KIND_CALENDAR)) == 1
    # 清空指定 kind
    db.clear_material(MATERIAL_KIND_CALENDAR)
    assert len(db.get_material(kind=MATERIAL_KIND_CALENDAR)) == 0
    assert len(db.get_material(kind=MATERIAL_KIND_SECTOR)) == 1
    db.clear_material()
    assert db.get_material() == []


def test_news_channel_normalizers():
    assert nc._norm_cls({"标题": "A", "内容": "B", "发布日期": "2026-10-17", "发布时间": "09:00"})["source"] == "财联社"
    assert nc._norm_cls({}) is None  # 空行跳过
    ths = nc._norm_ths({"标题": "T", "链接": "http://x", "发布时间": "10:00", "内容": "c"})
    assert ths["url"] == "http://x" and ths["source"] == "同花顺"
    futu = nc._norm_futu({"标题": "F", "链接": "http://y", "发布时间": "", "内容": "c"})
    # 发布时间为空时回退到当前时间
    assert futu["publish_time"]
    assert nc._norm_cctv({"title": "央视", "date": "2026", "content": "cc"})["source"] == "央视新闻"
    assert nc._norm_cx({"tag": "市场动态", "summary": "财新快讯正文", "url": "http://z"})["source"].startswith("财新")
    assert nc._norm_cx({"summary": ""}) is None
    # 新增来源：东方财富/新华网/巨潮资讯
    em = nc._norm_em({"标题": "E", "摘要": "s", "发布时间": "2026-10-18 09:00", "链接": "http://e"})
    assert em["source"] == "东方财富" and em["url"] == "http://e" and em["summary"] == "s"
    xh = nc._norm_xinhua({"标题": "新华网标题", "链接": "/fortune/20261018/aa/c.html", "发布时间": "2026-10-18"})
    assert xh["source"] == "新华网" and xh["url"] == "/fortune/20261018/aa/c.html"
    cn = nc._norm_cninfo({"标题": "公告标题", "证券代码": "600000", "证券名称": "浦发银行",
                          "发布时间": "2026-10-18 10:00", "链接": "https://static.cninfo.com.cn/x.pdf"})
    assert cn["source"].startswith("巨潮资讯网[浦发银行600000]") and cn["url"].endswith(".pdf")


def test_fetch_flash_news_unknown_channel(app_config):
    cfg = app_config.news
    cfg.channels = ["不存在的渠道"]
    # 未知渠道应被跳过并返回空（不触发网络）
    assert nc.fetch_flash_news(cfg) == []
