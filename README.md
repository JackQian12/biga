# A-Share Info Collector

可配置 AkShare/Tushare 数据源、token 认证 HTTP API、结合联网搜索的 LLM 智能解读的 A 股信息采集项目。

## 特性
- **可插拔数据源**：AkShare（免费）/ Tushare（需 token），config 切换。
- **token 认证**：`Authorization: Bearer <token>`。
- **盘中调度**：工作日内按间隔同步行情/基本面，抓取新闻。
- **多来源新闻聚合**：从财联社/同花顺/富途/央视/财新（akshare）聚合快讯，叠加联网搜索，
  统一入库 `news` 表（`/api/v1/news`）。
- **市场素材采集**：同步行业板块热度榜、财经数据日历等"素材"入库 `material` 表
  （`/api/v1/material`），供 AI 解读/日报参考板块与宏观方向。
- **结合联网搜索的 AI 解读**：`/api/v1/analyze` 会拉取该股本地行情+基本面+新闻+市场素材，
  再联网搜索补充实时上下文，一并注入你的 OpenAI 兼容 LLM 端点（默认 `http://192.168.50.46:8888/v1`）。
- **可插拔搜索**：默认自建爬虫（必应/百度结果页+正文抓取），内置反爬机制，也可切 mock 演示。
  - 反爬：UA 轮换、指数退避重试(403/429/5xx)、请求间随机延迟、Cookie 会话、可选代理、引擎间兜底。
- **企业微信订阅推送**：把自选股的行情+联网资讯交给 LLM 生成「A股情报日报」，定时/手动
  推送到企业微信群（群机器人，支持加签），为订阅用户提供 A 股情报服务。

## 安装
```bash
pip install -r requirements.txt
# 若用 tushare 数据源再装：
pip install tushare
```

## 配置
复制 `config.example.yaml` 为 `config.yaml`（已预置），按需修改：
- 数据源、token、LLM/base_url、搜索提供方与引擎。搜索 `provider: mock` 可本地演示不联网。

## 运行
```bash
python run.py --port 8000 --reload
```
- 接口文档：`http://127.0.0.1:8000/docs`
- 健康检查：`GET /health`
- 首次可先手动同步：`python -m app.scheduler_sync` （见说明）

## 认证示例
所有 `/api/v1/*` 接口需带：
```
Authorization: Bearer change-me-token-1
```

## 常用接口
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/v1/quotes | 全市场最新行情 |
| GET | /api/v1/quotes/{code} | 单股行情 |
| GET | /api/v1/fundamentals | 全市场基本面 |
| GET | /api/v1/fundamentals/{code} | 单股基本面 |
| GET | /api/v1/news?code= | 新闻（可按 code 过滤） |
| GET | /api/v1/material?kind=&limit= | 市场素材（板块热度 sector_heat / 财经日历 macro_calendar） |
| POST | /api/v1/analyze | AI 解读，body: `{"code":"600519","question":"...","use_search":true,"top_k":5}` |
| GET | /api/v1/subscriptions | 订阅分组列表 |
| POST | /api/v1/subscriptions | 新增订阅分组（webhook + 自选股） |
| PATCH | /api/v1/subscriptions/{id} | 更新订阅分组 |
| DELETE | /api/v1/subscriptions/{id} | 删除订阅分组 |
| POST | /api/v1/subscriptions/{id}/push | 手动向某分组推送日报 |
| POST | /api/v1/subscriptions/{id}/push-analyze | 对单只股票跑 AI 解读并推送给该分组，body: `{"code":"600519",...}` |
| POST | /api/v1/subscriptions/push-all | 向所有启用的分组推送日报 |
| GET | /health | 健康检查 |

## curl 示例
```bash
curl -H "Authorization: Bearer change-me-token-1" "http://127.0.0.1:8000/api/v1/quotes/600519"

curl -X POST -H "Authorization: Bearer change-me-token-1" -H "Content-Type: application/json" \
  -d '{"code":"600519","question":"今天怎么看？","use_search":true,"top_k":5}' \
  "http://127.0.0.1:8000/api/v1/analyze"
```

将 `config.yaml` 中 `wecom.enabled` 设为 true，并至少配置一种渠道（群机器人 `webhook_url`
或自建应用 `corpid/agentid/app_secret`），登记订阅分组与自选股代码后，
即会在每个交易日收盘后（默认 16:15）自动推送日报。两种渠道均支持 markdown 高亮，
<font color="info"></font> 等企业微信富文本标签。

```bash
# 登记一个订阅分组并绑定自选股
curl -X POST -H "Authorization: Bearer change-me-token-1" -H "Content-Type: application/json" \
  -d '{"name":"我的大盘群","webhook_url":"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx","watch_codes":["600519","000001"]}' \
  "http://127.0.0.1:8000/api/v1/subscriptions"

# 手动立即推送一份日报到该群
curl -X POST -H "Authorization: Bearer change-me-token-1" "http://127.0.0.1:8000/api/v1/subscriptions/1/push"

# 对单只股票跑 AI 解读后推送到该分组
curl -X POST -H "Authorization: Bearer change-me-token-1" -H "Content-Type: application/json" \
  -d '{"code":"600519","question":"今天怎么看","use_search":true}' \
  "http://127.0.0.1:8000/api/v1/subscriptions/1/push-analyze"
```

## 手动触发同步（开发用）
先启动数据源手动同步一次（akshare 未安装会直接报错提示）：
```powershell
python -c "from app.container import get_datasource; from app.config import get_config; print(get_datasource().check_available())"
```
或直接写一段：
```powershell
python -c "from app import database as db; from app.container import get_datasource; from app.config import get_config; from app.scheduler import sync_market; print(sync_market())"
```
