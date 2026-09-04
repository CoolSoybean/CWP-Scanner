# CWP Scanner

日线级 S&P 500 / 沪深300结构扫描器。项目按五层拆分：行情数据、CWP策略引擎、批量扫描、观察名单生命周期和通知。

## Codex 接手顺序

开始修改前依次阅读：

1. [`AGENTS.md`](AGENTS.md)：强制规则、职责边界和完成标准；
2. [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)：业务背景、完整架构、调用链和后续优先级；
3. [`reference/CWP1.8.5.pine.txt`](reference/CWP1.8.5.pine.txt)：不可擅自改变语义的策略真源；
4. [`docs/PORTING_NOTES.md`](docs/PORTING_NOTES.md)：Pine 到 Python 的移植说明。

## 当前版本边界

当前包版本：`0.4.0`；策略引擎标识仍为 `1.8.5-source-port`。`0.3.0` 将沪深300
数据源由 AKShare 切换为 Baostock，并将 S&P 500 成分股读取方式改为
Wikipedia MediaWiki API；`0.3.1` 让现有 `TELEGRAM_CHAT_ID` 支持多个接收方；`0.4.0`
为沪深300增加短窗口增量下载、前复权基准变化检测、失败重试、运行进度和元数据。
策略信号定义和引擎执行顺序没有改变。

`engine/cwp_engine.py` 已按提供的 Pine V1.8.5 源码第2–27节重新实现为 **V1.8.5 source port**，覆盖：

- TradingView Wilder ATR及波动率缩放；
- 确认分型、交替笔、同类极值替换、最小bar及ATR幅度过滤；
- 三笔重叠中枢、延伸/切换、Break注册和Chan Regime；
- Micro Pivot / BOS、PA Sweep和Engulfing；
- 1B→2B、1S→2S完整生命周期；
- SC/BC→ST→Accumulation/Distribution；
- Spring/UTAD确认与失效；
- 中枢Break、3B/3S回踩和最终Entry优先级；
- Setup专属结构止损、结构TP1、2R/3R及风险生命周期。

`scan_history()` 会输出逐Bar内部状态，供源码派生回归测试使用。

由于TradingView样本无法导出，当前结论是“源码语义级移植并通过本地构造场景验证”，不能声称已经完成TradingView逐Bar数值100% parity。剩余不确定性主要是TradingView内置 `ta.pivothigh/ta.pivotlow` 在极少数相等高低点场景的边界语义，以及不同数据源的复权和成交量口径。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows PowerShell：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 本地运行

首次下载并扫描 S&P 500：

```bash
python -m scanner.scanner --market sp500 --bars 800
```

首次下载并扫描沪深300：

```bash
python -m scanner.scanner --market hs300 --bars 800
```

只使用仓库已有 Parquet 缓存：

```bash
python -m scanner.scanner --market sp500 --no-download
python -m scanner.scanner --market hs300 --no-download
```

强制完整刷新沪深300前复权历史：

```bash
python -m scanner.scanner --market hs300 --bars 800 --force-full-download
```

生成通知文本但不发送：

```bash
python -m scanner.scanner --market sp500 --notify --dry-run-notifications
```

正式发送 Telegram：

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="123456789,-1001234567890"
python -m scanner.scanner --market sp500 --notify
```

`TELEGRAM_CHAT_ID` 支持单个 ID，也支持用英文逗号分隔多个用户或群组 ID。程序会
去除空格、空值和重复项，再将同一消息依次发送给每个接收方。每个用户需要先向 Bot
发送 `/start`；群组通常使用负数 ID，并需要先将 Bot 加入群组。不要将 Token 或真实
chat ID 写入代码、workflow、日志或 Artifact。

首次建立观察名单时只发送汇总，不逐只推送所有现存 READY/ENTRY；从第二次扫描开始才发送状态变化提醒，避免初始化消息轰炸。

## 数据来源及口径

| 市场 | 成分股 | 日线 | 调整口径 |
|---|---|---|---|
| S&P 500 | Wikipedia MediaWiki API | Yahoo Finance / `yfinance` | `auto_adjust=True` |
| 沪深300 | Baostock `query_hs300_stocks` | `query_history_k_data_plus` 日线 | 前复权 `adjustflag=2` |

免费源适合个人研究扫描，不应默认用于商业分发、正式估值或自动下单。使用前需自行核查数据许可、稳定性、复权差异和延迟。

### 沪深300 / Baostock

- 股票代码按交易所转换，例如 `600519 -> sh.600519`、`000001 -> sz.000001`；
- 日线字段为 `date, open, high, low, close, volume, tradestatus`；
- 只保留 `tradestatus=1` 的正常交易记录，不对停牌日填充价格；
- Baostock 使用单一登录会话串行查询，不要在同一运行环境中并行登录或调用；
- 日常下载只请求最近45个自然日，并与缓存重叠日期的OHLC比较；
- 重叠价格发生变化、没有可靠重叠或缓存缺失时，自动完整刷新该股票的历史窗口，
  避免公司行动后把不同前复权基准拼接在一起；
- 单次 socket 等待默认30秒，查询默认重试两次；最终失败时记录错误、保留已有缓存并继续；
- 周五定时任务执行一次全量刷新，手动运行也可选择强制全量；
- 本地首次300只、每只约800根日线的完整测试耗时约15分钟，实际耗时取决于网络和服务状态。

Baostock 使用独立缓存。旧 AKShare 文件不会被新适配器读取或合并：

```text
当前使用：cache/hs300_baostock_daily.parquet
当前使用：cache/constituents/hs300_baostock.csv
旧版忽略：cache/hs300_daily.parquet
旧版忽略：cache/constituents/hs300.csv
```

### S&P 500 / MediaWiki API

成分股通过 MediaWiki `action=parse` API 获取，并发送项目专用 `User-Agent`。API
请求或页面解析失败时，如果已有成分股缓存，则回退到最后一次有效缓存。股票代码会按
Yahoo格式转换，例如 `BRK.B -> BRK-B`。

## 输出文件

```text
cache/sp500_daily.parquet          美股行情缓存
cache/hs300_baostock_daily.parquet A股Baostock行情缓存
cache/constituents/sp500.csv       标普500成分股缓存
cache/constituents/hs300_baostock.csv 沪深300成分股缓存
output/latest/sp500.csv            最新完整扫描结果
output/latest/hs300.csv
output/alerts/*_current.csv         当前ENTRY/READY
output/alerts/*_changes.csv         相对上次扫描的状态变化
output/reports/*_summary.md         每日摘要
output/reports/hs300_run_metadata.json 下载与扫描运行统计
state/watchlist.csv                 跨日观察名单
state/signal_history.csv            状态变化历史
state/notifications.json            通知去重状态
logs/scan_errors.log                单股票失败日志
```

## 扫描状态

| Rank | 状态 | 含义 |
|---:|---|---|
| 3 | ENTRY | 模型确认条件已触发 |
| 2 | READY | Setup已形成，等待确认 |
| 1 | WATCH | 市场结构值得持续观察 |
| 0 | NONE | 当前没有有效多头结构 |

信号代表模型检测事实，不代表买入或下单建议。

## Parity验证

1. 如未来可导出TradingView数据，将逐日信号字段放入 `parity/fixtures/pine_export.csv`。
2. 让 Python 对同一只股票、同一日期范围、同一复权口径输出同名字段。
3. 运行：

```bash
python -m parity.parity_test \
  --pine parity/fixtures/pine_export.csv \
  --python parity/fixtures/expected_signals.csv \
  --output output/parity_mismatches.csv
```

退出码为 `0` 代表指定字段无差异；`1` 代表存在差异。

## 测试

```bash
pytest -q
```

## GitHub配置

Repository → Settings → Actions → General：允许 workflow 读写仓库，或使用 workflow 中的：

```yaml
permissions:
  contents: write
```

Repository Secrets：

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID  # 单个ID，或英文逗号分隔的多个ID
```

GitHub Actions会把以下内容推回仓库：

- 最新行情缓存；
- 成分股缓存；
- 当前扫描结果；
- 观察名单及信号历史；
- 通知去重状态。

完整当次输出及错误日志另作为短期 Artifact 保存。

自动执行时间以 UTC 配置：

```text
沪深300：周一至周五 08:30 UTC（北京时间 16:30，周五执行全量刷新）
标普500：周一至周五 22:30 UTC
```

GitHub Actions 定时任务可能延迟数分钟，且工作日遇到市场休市时仍会触发。两个扫描
workflow 当前任务上限均为30分钟。手动触发 HS300 workflow 时可通过
`force_full_download` 选择完整刷新。

## 上线前检查

- 完成 V1.8.5 Pine → Python parity，而不仅是通过单元测试；
- 在无法导出TradingView状态时，运行 `python scripts/source_parity_smoke.py`；
- 确认 TradingView 与 Python 的拆股、分红和前复权口径一致；
- 使用至少20个典型样本覆盖 Spring、2B、3B、BRK、Gap和失效场景；
- 检查交易所休市日、数据源缺失和半日市；
- Telegram先运行两周 dry run，再决定通知阈值；
- 不将模型价格字段直接接入券商下单接口。
