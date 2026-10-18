# -*- coding: utf-8 -*-
"""基于 Tushare 的数据源实现（需真实 token）。

Tushare Pro 采用积分制的接口权限，字段名规范化与 akshare 对齐。
使用前需 `pip install tushare` 并在 config.yaml 配置 tushare_token。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import DataSource

logger = logging.getLogger(__name__)


def _f(val) -> float | None:
    try:
        return None if val is None else float(val)
    except (TypeError, ValueError):
        return None


class TushareDataSource(DataSource):

    def __init__(self, token: str = ""):
        self._token = token
        self._pro = None

    @property
    def name(self) -> str:
        return "tushare"

    def check_available(self) -> str:
        if not self._token:
            return "config.yaml 未配置 tushare_token，请填写"
        try:
            import tushare  # noqa: F401
            return "ok"
        except Exception as exc:
            return f"请先 pip install tushare：{exc}"

    def _require(self):
        if not self._token:
            raise RuntimeError("Tushare 需要配置 token（config.yaml -> data_source.tushare_token）")
        try:
            import tushare as ts
        except Exception as exc:
            raise RuntimeError("Tushare 未安装，请先 pip install tushare") from exc
        if self._pro is None:
            self._pro = ts.pro_api(self._token)
        return self._pro

    def fetch_quotes(self) -> List[Dict[str, Any]]:
        pro = self._require()
        try:
            # 全市场实时行情（需要较高积分）
            df = pro.stock_basic(list_status="L", fields="ts_code,symbol,name")
            symbols = df["ts_code"].tolist() if df is not None and not df.empty else []
        except Exception as exc:
            logger.warning("获取股票列表失败：%s", exc)
            symbols = []
        now = datetime.now().isoformat(timespec="seconds")
        result = []
        # 批量轮询接口此处做演示用；真实场景建议用 pro.realtime_quote 或限频。
        batch = symbols[:50]
        try:
            qdf = pro.realtime_quote(ts_code=",".join(batch) or None, fields=(
                "TS_CODE,NAME,PRICE,OPEN,HIGH,LOW,PRE_CLOSE,VOLUME,AMOUNT,CHANGE,CHANGE_PCT"
            ))
        except Exception as exc:
            logger.warning("realtime_quote 需要较高权限（%s），返回空。", exc)
            return []

        for r in qdf.to_dict("records") if qdf is not None else []:
            code = str(r.get("TS_CODE") or r.get("ts_code") or "").split(".")[0]
            if not code:
                continue
            result.append({
                "code": code,
                "name": str(r.get("NAME") or code),
                "price": _f(r.get("PRICE")),
                "open": _f(r.get("OPEN")),
                "high": _f(r.get("HIGH")),
                "low": _f(r.get("LOW")),
                "prev_close": _f(r.get("PRE_CLOSE")),
                "volume": _f(r.get("VOLUME")),
                "amount": _f(r.get("AMOUNT")),
                "change_pct": _f(r.get("CHANGE_PCT")),
                "change": _f(r.get("CHANGE")),
                "update_time": now,
            })
        return result

    def fetch_fundamentals(self) -> List[Dict[str, Any]]:
        # 每日基本面指标（含 pe/pb/roe/总市值等），需相应积分权限
        pro = self._require()
        trade_date = datetime.now().strftime("%Y%m%d")
        try:
            df = pro.daily_basic(
                trade_date=trade_date,
                fields="ts_code,pe,pb,roe, total_mv,eps,bps,rev_yoy,profit_yoy,dv_ttm",
            ).drop_duplicates(subset=["ts_code"])
        except Exception as exc:
            logger.warning("daily_basic(%s) 失败：%s（可能非交易日或积分不足）", trade_date, exc)
            return []
        now = datetime.now().isoformat(timespec="seconds")
        result = []
        for r in df.to_dict("records"):
            ts_code = str(r.get("ts_code") or "")
            code = ts_code.split(".")[0]
            if not code:
                continue
            result.append({
                "code": code,
                "name": "",
                "pe": _f(r.get("pe")),
                "pb": _f(r.get("pb")),
                "roe": _f(r.get("roe")),
                "market_cap": _f(r.get("total_mv")) * 1e6 if r.get("total_mv") is not None else None,  # 万元->元
                "eps": _f(r.get("eps")),
                "bvps": _f(r.get("bps")),
                "revenue_growth": _f(r.get("rev_yoy")),
                "profit_growth": _f(r.get("profit_yoy")),
                "dividend_yield": _f(r.get("dv_ttm")),
                "update_time": now,
            })
        return result

    def fetch_funds_flow(self, codes: List[str]) -> List[Dict[str, Any]]:
        """个股资金流向（moneyflow 接口，需要相应积分权限）。"""
        pro = self._require()
        out: List[Dict[str, Any]] = []
        for code in codes:
            ts_code = f"{code}.{'SH' if code.startswith('6') else 'SZ'}" if code.startswith(("6", "0", "3")) else code
            try:
                df = pro.moneyflow(ts_code=ts_code)
                if df is None or df.empty:
                    continue
                r = df.iloc[0]
                out.append({
                    "code": code,
                    "main_net_inflow": _f(r.get("net_mf_amount")),
                    "super_net_inflow": _f(r.get("buy_elg_amount")) - (_f(r.get("sell_elg_amount")) or 0) if r.get("buy_elg_amount") is not None and r.get("sell_elg_amount") is not None else None,
                    "large_net_inflow": _f(r.get("buy_lg_amount")) - (_f(r.get("sell_lg_amount")) or 0) if r.get("buy_lg_amount") is not None and r.get("sell_lg_amount") is not None else None,
                    "medium_net_inflow": None,
                    "small_net_inflow": None,
                    "main_change_pct": None,
                    "date": str(r.get("trade_date") or ""),
                    "update_time": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as exc:
                logger.warning("tushare 资金流向失败 %s：%s", code, exc)
                continue
        return out

    def fetch_shareholders(self, codes: List[str]) -> List[Dict[str, Any]]:
        """股本结构与股东户数（stock_company / stk_holdernumber 接口）。"""
        pro = self._require()
        out: List[Dict[str, Any]] = []
        for code in codes:
            ts_code = f"{code}.SH" if code.startswith("6") else (f"{code}.SZ" if code.startswith(("0", "3")) else code)
            rec = {"code": code, "name": "", "total_share": None, "float_share": None,
                   "total_mv": None, "float_mv": None, "holders": None,
                   "holders_change_pct": None, "report_date": "",
                   "update_time": datetime.now().isoformat(timespec="seconds")}
            try:
                comp = pro.stock_company(ts_code=ts_code, fields="ts_code,chairman,reg_capital,list_date")
                # reg_capital 单位为万元、按面值折算总股本比较繁琐，这里仅记录基本信息
            except Exception:
                pass
            try:
                hn = pro.stk_holdernumber(ts_code=ts_code)
                if hn is not None and not hn.empty:
                    hn = hn.sort_values("end_date", ascending=False).iloc[0]
                    rec["holders"] = _f(hn.get("holder_num"))
                    rec["report_date"] = str(hn.get("end_date") or "")
            except Exception as exc:
                logger.warning("tushare 股东户数失败 %s：%s", code, exc)
            out.append(rec)
        return out

    def fetch_technical(self, codes: List[str]) -> List[Dict[str, Any]]:
        """用 pro.daily 计算 MA/RSI/KDJ，并尽量取换手/量比。"""
        from .akshare_source import _ma, _rsi, _kdj
        pro = self._require()
        out: List[Dict[str, Any]] = []
        for code in codes:
            ts_code = f"{code}.SH" if code.startswith("6") else (f"{code}.SZ" if code.startswith(("0", "3")) else code)
            try:
                df = pro.daily(ts_code=ts_code, limit=80)
                if df is None or df.empty:
                    continue
                df = df.sort_values("trade_date")
                prices = [float(x) for x in df["close"].tolist() if x is not None]
                if not prices:
                    continue
                rec = {
                    "code": code,
                    "turnover_rate": _f(df.iloc[-1].get("turnover_rate")) if df.iloc[-1].get("turnover_rate") is not None else None,
                    "volume_ratio": None,
                    "ma5": _ma(prices, 5),
                    "ma10": _ma(prices, 10),
                    "ma20": _ma(prices, 20),
                    "ma60": _ma(prices, 60),
                    "rsi6": _rsi(prices, 6),
                    "rsi12": _rsi(prices, 12),
                    "rsi24": _rsi(prices, 24),
                    "kdj_k": None, "kdj_d": None, "kdj_j": None,
                    "date": str(df.iloc[-1].get("trade_date") or ""),
                    "update_time": datetime.now().isoformat(timespec="seconds"),
                }
                try:
                    k, d, j = _kdj(prices)
                    rec["kdj_k"], rec["kdj_d"], rec["kdj_j"] = k, d, j
                except Exception:
                    pass
                out.append(rec)
            except Exception as exc:
                logger.warning("tushare 技术指标失败 %s：%s", code, exc)
                continue
        return out
