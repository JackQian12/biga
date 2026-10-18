# -*- coding: utf-8 -*-
"""基于 AkShare 的数据源实现（免费，无需 token）。

AkShare 接口经常变动，因此统一在此封装并通过 auto_convert 处理数值列，
避免因缺列/类型变化导致写入失败。使用前需 `pip install akshare`。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .base import DataSource

logger = logging.getLogger(__name__)

_NUMBER_COLS = ["price", "open", "high", "low", "prev_close", "volume",
                 "amount", "change_pct", "change",
                 "pe", "pb", "roe", "market_cap", "eps", "bvps",
                 "revenue_growth", "profit_growth", "dividend_yield"]


def _to_float(val) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
        return f
    except (TypeError, ValueError):
        return None


def _market_of(code: str) -> str:
    """按代码前缀推断交易所（akshare 所用记号：sh/sz/bj）。"""
    c = str(code).strip()
    if c.startswith(("60", "68", "900")):
        return "sh"
    if c.startswith(("00", "20", "30")):
        return "sz"
    if c.startswith(("43", "83", "87", "88", "920")):
        return "bj"
    return "sz"


def _pick(row: Dict[str, Any], names) -> Any:
    """从行中取第一个存在的列（akshare 中文列名常随版本变动，因此容错查找）。"""
    for n in names:
        if row.get(n) is not None and str(row.get(n)) != "":
            return row.get(n)
    return None


def _norm_funds_flow(row: Dict[str, Any], code: str) -> Dict[str, Any]:
    """把 akshare 个股资金流行的中文列映射为库内键。"""
    return {
        "code": code,
        "main_net_inflow": _to_float(_pick(row, ["主力净流入-净额", "主力净流入", "主力净流入-净额"])),
        "super_net_inflow": _to_float(_pick(row, ["超大单净流入-净额", "超大单净流入"])),
        "large_net_inflow": _to_float(_pick(row, ["大单净流入-净额", "大单净流入"])),
        "medium_net_inflow": _to_float(_pick(row, ["中单净流入-净额", "中单净流入"])),
        "small_net_inflow": _to_float(_pick(row, ["小单净流入-净额", "小单净流入"])),
        "main_change_pct": _to_float(_pick(row, ["主力净流入-占比", "主力净流入-净占比"])),
        "date": _pick(row, ["日期"]) or "",
        "update_time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


def _norm_shareholders(row: Dict[str, Any], code: str = "") -> Dict[str, Any]:
    """把 akshare 股东/股本行的中文列映射为库内键。"""
    return {
        "code": code,
        "name": str(_pick(row, ["名称", "股票简称"]) or ""),
        "total_share": _to_float(_pick(row, ["总股本", "总股本(股)", "总股本"])) or _to_float(_pick(row, ["总股本"])),
        "float_share": _to_float(_pick(row, ["流通股本", "流通股本(股)", "流通股"])),
        "total_mv": _to_float(_pick(row, ["总市值"])),
        "float_mv": _to_float(_pick(row, ["流通市值"])),
        "holders": _to_float(_pick(row, ["股东户数", "股东户数-合计"])),
        "holders_change_pct": _to_float(_pick(row, ["较上期变化", "股东户数增减"])) ,
        "report_date": str(_pick(row, ["截止日期", "报告期"]) or ""),
        "update_time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


def _norm_technical(row: Dict[str, Any], code: str = "") -> Dict[str, Any]:
    """把 akshare 技术指标行映射为库内键。"""
    return {
        "code": code,
        "turnover_rate": _to_float(_pick(row, ["换手率", "换手"])),
        "volume_ratio": _to_float(_pick(row, ["量比"])),
        "ma5": _to_float(_pick(row, ["MA5", "ma5"])),
        "ma10": _to_float(_pick(row, ["MA10", "ma10"])),
        "ma20": _to_float(_pick(row, ["MA20", "ma20"])),
        "ma60": _to_float(_pick(row, ["MA60", "ma60"])),
        "rsi6": _to_float(_pick(row, ["RSI6", "rsi6"])),
        "rsi12": _to_float(_pick(row, ["RSI12", "rsi12"])),
        "rsi24": _to_float(_pick(row, ["RSI24", "rsi24"])),
        "macd_dif": _to_float(_pick(row, ["DIF", "MACD DIF"])),
        "macd_dea": _to_float(_pick(row, ["DEA", "MACD DEA"])),
        "macd_bar": _to_float(_pick(row, ["MACD", "macd", "MACD柱"])),
        "kdj_k": _to_float(_pick(row, ["K", "KDJ-K"])),
        "kdj_d": _to_float(_pick(row, ["D", "KDJ-D"])),
        "kdj_j": _to_float(_pick(row, ["J", "KDJ-J"])),
        "date": str(_pick(row, ["日期"]) or ""),
        "update_time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }


def _row_to_record(row: Dict[str, Any], *, kind: str) -> Dict[str, Any]:
    """把 akshare 的字典行规范化成我们库里的记录。字段名按中文常见映射。"""
    code = (row.get("代码") or row.get("股票代码") or row.get("code") or "").strip()
    name = (row.get("名称") or row.get("股票简称") or row.get("name") or code)
    name = str(name).strip()

    if kind == "quote":
        return {
            "code": code,
            "name": name,
            "price": _to_float(row.get("最新价") or row.get("price")),
            "open": _to_float(row.get("今开") or row.get("open")),
            "high": _to_float(row.get("最高") or row.get("high")),
            "low": _to_float(row.get("最低") or row.get("low")),
            "prev_close": _to_float(row.get("昨收") or row.get("昨收") or row.get("prev_close")),
            "volume": _to_float(row.get("成交量") or row.get("volume")),
            "amount": _to_float(row.get("成交额") or row.get("amount")),
            "change_pct": _to_float(row.get("涨跌幅") or row.get("change_pct")),
            "change": _to_float(row.get("涨跌额") or row.get("change")),
        }

    if kind == "fundamental":
        return {
            "code": code,
            "name": name,
            "pe": _to_float(row.get("市盈率") or row.get("pe")),
            "pb": _to_float(row.get("市净率") or row.get("pb")),
            "roe": _to_float(row.get("净资产收益率") or row.get("roe")),
            "market_cap": _to_float(row.get("总市值") or row.get("market_cap")),
            "eps": _to_float(row.get("每股收益") or row.get("eps")),
            "bvps": _to_float(row.get("每股净资产") or row.get("bvps")),
            "revenue_growth": _to_float(row.get("营业收入同比增长") or row.get("revenue_growth")),
            "profit_growth": _to_float(row.get("净利润同比增长") or row.get("profit_growth")),
            "dividend_yield": _to_float(row.get("股息率") or row.get("dividend_yield")),
        }
    return {}


def _ma(prices: List[float], n: int) -> float | None:
    if len(prices) < n:
        return None
    return round(sum(prices[-n:]) / n, 4)


def _rsi(prices: List[float], n: int) -> float | None:
    """简单 RSI 实现（取最近 n 根 K 线，尾部平滑近似）。"""
    if len(prices) < n + 1:
        return None
    gains = losses = 0.0
    deltas = [prices[i] - prices[i - 1] for i in range(len(prices) - n, len(prices))]
    for d in deltas:
        if d > 0:
            gains += d
        else:
            losses += -d
    if gains + losses == 0:
        return 50.0
    return round(100 * gains / (gains + losses), 2)


def _kdj(prices: List[float]) -> tuple:
    """简单 KDJ 实现（9 日 RSV）。返回 (K, D, J)。"""
    window = 9
    if len(prices) < window:
        return None, None, None
    k = d = 50.0
    k_val = d_val = None
    for i in range(window - 1, len(prices)):
        chunk = prices[i - window + 1: i + 1]
        low = min(chunk)
        high = max(chunk)
        rsv = (prices[i] - low) / (high - low) * 100 if high != low else 50.0
        k = 2 / 3 * k + 1 / 3 * rsv
        d = 2 / 3 * d + 1 / 3 * k
    j = 3 * k - 2 * d
    return round(k, 2), round(d, 2), round(j, 2)


class AkShareDataSource(DataSource):

    @property
    def name(self) -> str:
        return "akshare"

    def check_available(self) -> str:
        try:
            import akshare  # noqa: F401
            return "ok"
        except Exception as exc:
            return f"请先 pip install akshare：{exc}"

    @staticmethod
    def _import_ak():
        try:
            import akshare as ak
            return ak
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"AkShare 未安装或导入失败，请先安装：pip install akshare，详情：{exc}") from exc

    def fetch_quotes(self) -> List[Dict[str, Any]]:
        ak = self._import_ak()
        try:
            raw = ak.stock_zh_a_spot_em().to_dict("records")
        except Exception as exc:
            # 兼容老版本接口
            raw = ak.stock_zh_a_spot().to_dict("records")
            logger.warning("stock_zh_a_spot_em 不可用(%s)，回退 stock_zh_a_spot", exc)
        result = []
        for row in raw:
            rec = _row_to_record(row, kind="quote")
            if rec.get("code"):
                now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
                rec["update_time"] = now
                result.append(rec)
        return result

    def fetch_fundamentals(self) -> List[Dict[str, Any]]:
        # 全市场行情快照自带实时估值字段（市盈率-动态/市净率/总市值），
        # 直接复用该快照提取基础基本面，速度快且覆盖全 A。
        ak = self._import_ak()
        try:
            raw = ak.stock_zh_a_spot_em().to_dict("records")
        except Exception:
            raw = []
        result = []
        for row in raw:
            code = (row.get("代码") or row.get("股票代码") or "").strip()
            if not code:
                continue
            name = (row.get("名称") or row.get("股票简称") or code)
            now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
            result.append({
                "code": code,
                "name": str(name).strip(),
                "pe": _to_float(row.get("市盈率-动态") or row.get("市盈率-静") or row.get("pe")),
                "pb": _to_float(row.get("市净率") or row.get("pb")),
                "roe": _to_float(row.get("净资产收益率") or row.get("roe")),
                "market_cap": _to_float(row.get("总市值") or row.get("market_cap")),
                "eps": _to_float(row.get("每股收益") or row.get("eps")),
                "bvps": _to_float(row.get("每股净资产") or row.get("bvps")),
                "revenue_growth": _to_float(row.get("营收同比") or row.get("revenue_growth")),
                "profit_growth": _to_float(row.get("净利润同比") or row.get("profit_growth")),
                "dividend_yield": _to_float(row.get("股息率") or row.get("dividend_yield")),
                "update_time": now,
            })
        return result

    def fetch_funds_flow(self, codes: List[str]) -> List[Dict[str, Any]]:
        """按代码实时抓取个股资金流向（主力/超大单/大单/中单/小单净流入）。"""
        ak = self._import_ak()
        out: List[Dict[str, Any]] = []
        for code in codes:
            try:
                market = _market_of(code)
                df = ak.stock_individual_fund_flow(stock=code, market=market)
                if df is None or df.empty:
                    continue
                # 最新一日资金流向取最后一行
                row = df.iloc[-1].to_dict()
                out.append(_norm_funds_flow(row, code))
            except Exception as exc:
                logger.warning("资金流向抓取失败 %s：%s", code, exc)
                continue
        return out

    def fetch_shareholders(self, codes: List[str]) -> List[Dict[str, Any]]:
        """按代码抓取个股股本结构/股东信息。

        优先用公司信息接口（总股本/流通股本/总市值/流通市值）；
        再补充股东户数接口（全市场按代码过滤取最新一条）。
        """
        ak = self._import_ak()
        out: List[Dict[str, Any]] = []
        holder_rows: Dict[str, Dict[str, Any]] = {}
        try:
            gdhs = ak.stock_zh_a_gdhs()  # 全市场股东户数
            if gdhs is not None and not gdhs.empty:
                for r in gdhs.to_dict("records"):
                    c = str(_pick(r, ["代码", "股票代码"]) or "").strip()
                    if c:
                        holder_rows[c] = r
        except Exception as exc:
            logger.warning("股东户数抓取失败：%s", exc)

        for code in codes:
            info = {}
            try:
                df = ak.stock_individual_info_em(symbol=code)
                if df is not None and not df.empty:
                    info = dict(zip(df["item"].tolist(), df["value"].tolist()))
            except Exception as exc:
                logger.warning("公司信息接口失败 %s：%s", code, exc)

            merged = dict(info)
            hrow = holder_rows.get(str(code))
            if hrow:
                merged.update(hrow)
            merged["代码"] = code
            merged["名称"] = merged.get("名称") or merged.get("股票简称") or code
            rec = _norm_shareholders(merged, code)
            # 只保留至少有一项有效数据的结果
            if any(v is not None for v in (rec["total_share"], rec["float_share"], rec["holders"])):
                out.append(rec)
        return out

    def fetch_technical(self, codes: List[str]) -> List[Dict[str, Any]]:
        """按代码抓取/计算技术指标（换手率/量比/MA/RSI/KDJ/MACD）。"""
        ak = self._import_ak()
        out: List[Dict[str, Any]] = []
        for code in codes:
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
                if df is None or df.empty:
                    continue
                df = df.tail(80)
                prices = [float(x) for x in df["收盘"].tolist() if x is not None]
                if not prices:
                    continue
                last = prices[-1]
                rec = {
                    "code": code,
                    "turnover_rate": _to_float(df.iloc[-1].get("换手率")),
                    "volume_ratio": _to_float(df.iloc[-1].get("量比")),
                    "ma5": _ma(prices, 5),
                    "ma10": _ma(prices, 10),
                    "ma20": _ma(prices, 20),
                    "ma60": _ma(prices, 60),
                    "rsi6": _rsi(prices, 6),
                    "rsi12": _rsi(prices, 12),
                    "rsi24": _rsi(prices, 24),
                    "kdj_k": None,
                    "kdj_d": None,
                    "kdj_j": None,
                    "date": str(df.iloc[-1].get("日期") or ""),
                    "update_time": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                }
                try:
                    k, d, j = _kdj(prices)
                    rec["kdj_k"], rec["kdj_d"], rec["kdj_j"] = k, d, j
                except Exception:
                    pass
                out.append(rec)
            except Exception as exc:
                logger.warning("技术指标抓取失败 %s：%s", code, exc)
                continue
        return out
