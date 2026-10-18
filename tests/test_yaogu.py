# -*- coding: utf-8 -*-
"""妖股资金溯源模块的单元测试：mock 三个 akshare 接口，验证筛选/汇总/判断与 Markdown 渲染逻辑。

不发起真实网络请求，通过 monkeypatch 替换 akshare 模块属性。
"""
from __future__ import annotations

import pandas as pd
import pytest

import akshare
from app.services import yaogu_trace as yt


def _make_zt_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"序号": 1, "代码": "600825", "名称": "新华传媒", "涨跌幅": 10.01, "最新价": 15.16,
         "成交额": 8e8, "流通市值": 1e10, "总市值": 1.2e10, "换手率": 5.5,
         "封板资金": 908271953, "首次封板时间": "092500", "最后封板时间": "092500",
         "炸板次数": 0, "涨停统计": "11/11", "连板数": 11, "所属行业": "出版"},
        {"序号": 2, "代码": "603999", "名称": "读者传媒", "涨跌幅": 9.97, "最新价": 8.38,
         "成交额": 2e8, "流通市值": 3e9, "总市值": 4e9, "换手率": 8.0,
         "封板资金": 111721154, "首次封板时间": "092501", "最后封板时间": "092501",
         "炸板次数": 0, "涨停统计": "2/2", "连板数": 2, "所属行业": "出版"},
    ])


def _make_lhb_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"序号": 1, "代码": "600825", "名称": "新华传媒", "上榜日": "2026-10-09",
         "解读": "2家机构买入，成功率20.44%", "收盘价": 15.16, "涨跌幅": 10.01,
         "龙虎榜净买额": 49771300.0, "龙虎榜买入额": 2e8, "龙虎榜卖出额": 1.5e8,
         "龙虎榜成交额": 3.5e8, "市场总成交额": 8e8, "净买额占总成交比": 6.2,
         "成交额占总成交比": 43.7, "换手率": 5.5, "流通市值": 1e10, "上榜原因": "连续三日涨幅偏离累计20%"},
        {"序号": 2, "代码": "603999", "名称": "读者传媒", "上榜日": "2026-10-16",
         "解读": "买一主买，成功率37.84%", "收盘价": 8.38, "涨跌幅": 9.97,
         "龙虎榜净买额": 75544800.0, "龙虎榜买入额": 1e8, "龙虎榜卖出额": 2.5e7,
         "龙虎榜成交额": 1.25e8, "市场总成交额": 2e8, "净买额占总成交比": 37.7,
         "成交额占总成交比": 62.5, "换手率": 8.0, "流通市值": 3e9, "上榜原因": "日换手率达20%"},
    ])


def _make_jg_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"序号": 1, "代码": "600825", "名称": "新华传媒", "收盘价": 15.16, "涨跌幅": 10.01,
         "买方机构数": 2, "卖方机构数": 0, "机构买入总额": 1.6e8, "机构卖出总额": 0.0,
         "机构买入净额": 1.2e8, "市场总成交额": 8e8, "机构净买额占总成交额比": 15.0,
         "换手率": 5.5, "流通市值": 1e10, "上榜原因": "连续三日涨幅偏离累计20%", "上榜日期": "2026-10-09"},
    ])


@pytest.fixture(autouse=True)
def _patch_ak(monkeypatch):
    """把三个 akshare 接口替换为假数据（假数据仅识别少数 occupied 日期均可）。"""
    monkeypatch.setattr(akshare, "stock_zt_pool_em", lambda *a, **k: _make_zt_df())
    monkeypatch.setattr(akshare, "stock_lhb_detail_em", lambda *a, **k: _make_lhb_df())
    monkeypatch.setattr(akshare, "stock_lhb_jgmmtj_em", lambda *a, **k: _make_jg_df())


def test_fetch_yaogu_trace_fields_and_order():
    res = yt.fetch_yaogu_trace(top_n=8, back_days=5)
    assert res["error"] is None
    rows = {r["代码"]: r for r in res["rows"]}
    assert {"600825", "603999"} <= set(rows)

    top = res["rows"][0]
    assert top["连板数"] == 11  # 连板数最高在前
    assert "600825" in [r["代码"] for r in res["rows"]]

    # 机构净买额 1.2e8 汇总成功
    assert abs(rows["600825"]["机构净买额"] - 1.2e8) < 1e-3
    # 读者传媒无机构标注、机构统计为空 → 净买额 0
    assert rows["603999"]["机构净买额"] == 0


def test_judge_inst_buy():
    m = {"上榜日": ["2026-10-09"], "解读": ["2家机构买入"], "机构净买额": 1.2e8,
         "买方机构数": 2, "卖方机构数": 0}
    assert "机构资金有迹可循" in yt._judge(m)


def test_judge_inst_sell():
    m = {"上榜日": ["2026-10-09"], "解读": ["1家机构卖出"], "机构净买额": -26822603.0,
         "买方机构数": 1, "卖方机构数": 2}
    out = yt._judge(m)
    assert "机构净卖出" in out and "2682.26万" in out


def test_judge_no_inst():
    m = {"上榜日": ["2026-10-16"], "解读": ["买一主买"], "机构净买额": 0.0,
         "买方机构数": 0, "卖方机构数": 0}
    assert "游资/席位" in yt._judge(m)


def test_judge_no_lhb():
    m = {"上榜日": [], "解读": [], "机构净买额": 0.0, "买方机构数": 0, "卖方机构数": 0}
    assert "未上龙虎榜" in yt._judge(m)


def test_format_yaogu_md_contains_sections():
    lines = yt.format_yaogu_md(top_n=8, back_days=5)
    text = "\n".join(lines)
    assert text.startswith("## 六、妖股资金溯源")
    assert "新华传媒" in text
    assert "龙虎榜席位线索" in text
    assert "600825" in text
    # 负数金额格式化正确
    assert any("-2682.26万" not in ln for ln in lines)


def test_fmt_amount():
    assert yt._fmt_amount(1.2e8) == "1.20亿"
    assert yt._fmt_amount(-26822603.0) == "-2682.26万"
    assert yt._fmt_amount(87914378) == "8791.44万"
    assert yt._fmt_amount(None) == "-"
