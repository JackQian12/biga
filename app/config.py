# -*- coding: utf-8 -*-
"""配置加载：从 config.yaml 读取，映射到类型安全的 Pydantic 模型。

支持通过环境变量前缀 BIGA_ 覆盖任意字段，例如：
    BIGA_LLM__MODEL=xxx           # 覆盖 llm.model
    BIGA_DATA_SOURCE__PROVIDER=tushare
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CFG = BASE_DIR / "config.yaml"
EXAMPLE_CFG = BASE_DIR / "config.example.yaml"


@dataclass
class DataSourceCfg:
    provider: str = "akshare"
    tushare_token: str = ""


@dataclass
class ScheduleCfg:
    market_sync_interval_seconds: int = 900
    news_interval_seconds: int = 3600
    update_market_only_in_trading: bool = True


@dataclass
class StorageCfg:
    sqlite_path: str = "./data/biga.db"


@dataclass
class AuthCfg:
    api_tokens: List[str] = field(default_factory=lambda: ["change-me-token-1"])
    header_name: str = "Authorization"
    scheme: str = "Bearer"


@dataclass
class LLMCfg:
    base_url: str = "http://192.168.50.46:8888/v1"
    model: str = ""
    api_key: str = ""
    temperature: float = 0.3
    timeout: int = 90


@dataclass
class SearchCfg:
    provider: str = "bing"          # bing | baidu | mock
    engine: str = "bing"
    top_k: int = 5
    timeout: int = 15
    user_agent: str = ""  # 兼容旧配置；为空则使用轮换 UA 池 (user_agents)
    user_agents: List[str] = field(default_factory=list)   # UA 轮换池
    proxy_url: str = ""               # 可选代理，如 http://127.0.0.1:7890
    retries: int = 3                  # 反爬：退避重试次数
    backoff: float = 1.5              # 反爬：指数退避基数
    enable_delay: bool = True         # 反爬：请求间随机延迟
    min_delay: float = 0.4
    max_delay: float = 1.6
    fetch_content: bool = True        # 是否抓取结果正文
    result_selector: str = ""
    snippet_selector: str = ""


@dataclass
class NewsCfg:
    channels: List[str] = field(default_factory=lambda: ["cls", "ths", "futu", "cctv", "cx", "sina"])
    limit_per_channel: int = 15       # 每个新闻渠道最多入库条数
    material: bool = True             # 是否采集市场素材（板块热度/财经日历）
    material_sector_top: int = 20     # 板块热度榜条数
    material_calendar_top: int = 10   # 财经日历条数


@dataclass
class WecomCfg:
    enabled: bool = False             # 是否启用企业微信推送
    webhook_url: str = ""             # 群机器人 Webhook 地址（渠道 1）
    webhook_secret: str = ""          # 加签密钥（未加签可留空）
    # 企业微信自建应用消息推送（渠道 2；配置了 corpid/agentid/app_secret 后，
    # 未单独配置 webhook 的订阅分组默认走该渠道，touser 默认 @all 全体成员）
    corpid: str = ""
    agentid: str = ""
    app_secret: str = ""
    app_touser: str = "@all"
    daily_push_time: str = "16:15"    # 每日日报推送时间（交易日）
    push_morning_time: str = ""       # 可选的盘前简报时间，留空则不推



@dataclass
class AppConfig:
    data_source: DataSourceCfg = field(default_factory=DataSourceCfg)
    schedule: ScheduleCfg = field(default_factory=ScheduleCfg)
    storage: StorageCfg = field(default_factory=StorageCfg)
    auth: AuthCfg = field(default_factory=AuthCfg)
    llm: LLMCfg = field(default_factory=LLMCfg)
    search: SearchCfg = field(default_factory=SearchCfg)
    news: NewsCfg = field(default_factory=NewsCfg)
    wecom: WecomCfg = field(default_factory=WecomCfg)
    config_path: Path = DEFAULT_CFG

    @property
    def db_path(self) -> Path:
        p = Path(self.storage.sqlite_path)
        return p if p.is_absolute() else (BASE_DIR / p)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两字典，override 优先。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _find_in(d: dict, keys: list):
    """沿 keys 找默认值，用于环境变量回退。"""
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg_path = Path(path) if path else DEFAULT_CFG
    example_raw: dict = {}
    try:
        with open(EXAMPLE_CFG, encoding="utf-8") as f:
            example_raw = yaml.safe_load(f) or {}
    except Exception:
        example_raw = {}

    raw: dict = {}
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            raw = {}

    merged = _deep_merge(example_raw, raw)

    # 环境变量覆盖
    def _env_overlay(dotted, current):
        env_key = "BIGA_" + dotted.upper().replace(".", "__")
        val = os.getenv(env_key)
        if val is None:
            return current
        if isinstance(current, bool):
            return val.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(current, int):
            try:
                return int(val)
            except ValueError:
                return current
        if isinstance(current, float):
            try:
                return float(val)
            except ValueError:
                return current
        if isinstance(current, list):
            return [x.strip() for x in val.split(",") if x.strip()]
        return val

    def apply_env(node, prefix=""):
        for k, v in list(node.items()):
            dotted = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                apply_env(v, dotted)
            else:
                default_v = _find_in(example_raw, dotted.split("."))
                node[k] = _env_overlay(dotted, v if v is not None else default_v)

    apply_env(merged)

    ds = merged.get("data_source", {}) or {}
    sch = merged.get("schedule", {}) or {}
    sto = merged.get("storage", {}) or {}
    aut = merged.get("auth", {}) or {}
    llm = merged.get("llm", {}) or {}
    src = merged.get("search", {}) or {}
    nw = merged.get("news", {}) or {}
    wc = merged.get("wecom", {}) or {}

    config = AppConfig(
        data_source=DataSourceCfg(
            provider=str(ds.get("provider", "akshare")),
            tushare_token=str(ds.get("tushare_token", "")),
        ),
        schedule=ScheduleCfg(
            market_sync_interval_seconds=int(sch.get("market_sync_interval_seconds", 900)),
            news_interval_seconds=int(sch.get("news_interval_seconds", 3600)),
            update_market_only_in_trading=bool(sch.get("update_market_only_in_trading", True)),
        ),
        storage=StorageCfg(sqlite_path=str(sto.get("sqlite_path", "./data/biga.db"))),
        auth=AuthCfg(api_tokens=list(aut.get("api_tokens", []) or ["change-me-token-1"])),
        llm=LLMCfg(
            base_url=str(llm.get("base_url", "http://192.168.50.46:8888/v1")),
            model=str(llm.get("model", "")),
            api_key=str(llm.get("api_key", "")),
            temperature=float(llm.get("temperature", 0.3)),
            timeout=int(llm.get("timeout", 90)),
        ),
        search=SearchCfg(
            provider=str(src.get("provider", "bing")),
            engine=str(src.get("engine", "bing")),
            top_k=int(src.get("top_k", 5)),
            timeout=int(src.get("timeout", 15)),
            user_agent=str(src.get("user_agent", "")),
            user_agents=list(src.get("user_agents", []) or []),
            proxy_url=str(src.get("proxy_url", "")),
            retries=int(src.get("retries", 3)),
            backoff=float(src.get("backoff", 1.5)),
            enable_delay=bool(src.get("enable_delay", True)),
            min_delay=float(src.get("min_delay", 0.4)),
            max_delay=float(src.get("max_delay", 1.6)),
            fetch_content=bool(src.get("fetch_content", True)),
            result_selector=str(src.get("result_selector", "")),
            snippet_selector=str(src.get("snippet_selector", "")),
        ),
        news=NewsCfg(
            channels=list(nw.get("channels", []) or ["cls", "ths", "futu", "cctv", "cx", "sina"]),
            limit_per_channel=int(nw.get("limit_per_channel", 15)),
            material=bool(nw.get("material", True)),
            material_sector_top=int(nw.get("material_sector_top", 20)),
            material_calendar_top=int(nw.get("material_calendar_top", 10)),
        ),
        wecom=WecomCfg(
            enabled=bool(wc.get("enabled", False)),
            webhook_url=str(wc.get("webhook_url", "")),
            webhook_secret=str(wc.get("webhook_secret", "")),
            corpid=str(wc.get("corpid", "")),
            agentid=str(wc.get("agentid", "")),
            app_secret=str(wc.get("app_secret", "")),
            app_touser=str(wc.get("app_touser", "@all")),
            daily_push_time=str(wc.get("daily_push_time", "16:15")),
            push_morning_time=str(wc.get("push_morning_time", "")),
        ),
        config_path=cfg_path,
    )
    return config


_config_singleton: AppConfig | None = None


def get_config() -> AppConfig:
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


def reload_config() -> AppConfig:
    global _config_singleton
    _config_singleton = load_config()
    return _config_singleton

