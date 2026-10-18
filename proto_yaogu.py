# -*- coding: utf-8 -*-
"""妖股/连板梯队 + 龙虎榜 数据可用性验证原型。

仅用于验证 akshare 相关接口能否拉到数据、字段是什么样，不做任何实盘建议。
用法：python proto_yaogu.py
"""
from __future__ import annotations

import datetime as dt
import sys


def _recent_trading_dates(n: int = 5) -> list[str]:
    """返回最近 n 个自然日（不含今天）的 YYYYMMDD，用于向前回退找交易日。"""
    today = dt.date.today()
    out = []
    d = today - dt.timedelta(days=1)
    while len(out) < n:
        out.append(d.strftime("%Y%m%d"))
        d -= dt.timedelta(days=1)
    return out


def _try(fn, *args) -> "object | None":
    try:
        return fn(*args)
    except Exception as exc:
        print(f"  ! 接口异常: {exc}")
        return None


def main() -> None:
    import akshare as ak

    dates = _recent_trading_dates(5)
    print(f"今天: {dt.date.today().isoformat()}，尝试回退日期: {dates}")
    print("=" * 60)

    # ---------- 1. 涨停股池（连板梯队） ----------
    zt = None
    for d in dates:
        df = _try(ak.stock_zt_pool_em, d)
        if df is not None and not df.empty:
            zt = (d, df)
            break
    if zt is None:
        print("涨停股池接口近 5 个自然日均无数据，请检查网络/东方财富接口可用性。")
    else:
        day, df = zt
        print(f"涨停股池 可用！日期={day} 行数={len(df)}")
        print("列:", list(df.columns))
        print("前 3 行:")
        print(df.head(3).to_string())
        # 连板梯队：按 连板数 字段排序取最高的几只
        if "连板数" in df.columns:
            top = df.nlargest(15, "连板数")[["代码", "名称", "最新价", "涨跌幅", "连板数", "所属行业", "封板资金", "最后封板时间"]]
            print("\n===== 连板梯队 TOP（按连板数） =====")
            print(top.to_string(index=False))
    print("=" * 60)

    # ---------- 2. 龙虎榜明细 ----------
    # 用最近的几个自然日覆盖到最近的 T+1 公布日
    start = (dt.date.today() - dt.timedelta(days=7)).strftime("%Y%m%d")
    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
    lhb = _try(ak.stock_lhb_detail_em, start, end)
    if lhb is None or lhb.empty:
        print("龙虎榜明细 近 7 天无数据（可能等待 T+1 公布）。")
    else:
        print(f"龙虎榜明细 可用！行数={len(lhb)} 日期范围 {start}~{end}")
        print("列:", list(lhb.columns))
        print(lhb.head(5).to_string())
    print("=" * 60)

    # ---------- 3. 机构买卖每日统计（游资/机构席位痕迹） ----------
    jg = _try(ak.stock_lhb_jgmmtj_em, start, end)
    if jg is None or jg.empty:
        print("机构买卖统计 近 7 天无数据。")
    else:
        print(f"机构买卖每日统计 可用！行数={len(jg)}")
        print("列:", list(jg.columns))
        print(jg.head(5).to_string())


if __name__ == "__main__":
    main()
