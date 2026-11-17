# Stock News Analysis（新闻与机构行为）

一个本地网页：首页看宏观数据和宏观新闻，输入股票代码看这只股票的新闻表格和机构行为。

- **只抓取和展示，不做 AI 打分。** 唯一的情绪标签是 Massive 随新闻附带的 `insights`，原样显示。
- **尽量免费。** 除了你已有的 Massive 和 FMP，其余来源都免费、不用注册。
- **和 investment-final-plan 同一套做法：** Python 3.11+ 标准库、原生 HTML/JS、只监听 127.0.0.1、key 只从环境变量读。暂时不接入 ifp。

## 快速开始（Windows）

1. 设置环境变量（只需一次）。打开 PowerShell，先看哪些 key 已经设了（只显示 set 或 not set，不显示值）：

   ```powershell
   cd C:\Users\Tim\Documents\claude\stock-news-analysis
   python -m sna status
   ```

   设 `SEC_USER_AGENT`。这是 SEC 的要求（写明是谁在访问，带联系邮箱），不设就不抓 SEC 文件。粘贴下面这一行回车，出现提示后输入你的名字和邮箱（例如 `Tim tim@example.com`）再回车：

   ```powershell
   [Environment]::SetEnvironmentVariable("SEC_USER_AGENT", (Read-Host "Name and email").Trim(), "User")
   ```

   如果 `MASSIVE_API_KEY` 显示 not set，粘贴下面这一行回车，出现提示后粘贴你的 Massive key 再回车。`FMP_API_KEY` 如果也是 not set，同样做法，把这一行里的 `MASSIVE_API_KEY` 换成 `FMP_API_KEY`：

   ```powershell
   [Environment]::SetEnvironmentVariable("MASSIVE_API_KEY", (Read-Host "Paste key").Trim(), "User")
   ```

   key 在提示里输入，不写在命令里，这样不会留在 PowerShell 的命令历史中。值只存在你电脑的用户环境变量里；不要写进文件，也不要贴到对话里。
   设完不用重开窗口，程序会直接读到；再跑一次 `python -m sna status` 确认变成 set。

2. 启动：

   ```powershell
   cd C:\Users\Tim\Documents\claude\stock-news-analysis
   python -m sna serve --open
   ```

   浏览器会打开 http://127.0.0.1:8790/ 。按 `/` 键随时搜索代码。

3. 第一次用建议跑一次自检，它会逐个实测所有来源，并核对 FMP 的时间基准：

   ```powershell
   python -m sna doctor --symbol NVDA
   ```

只想看看页面长什么样、不联网：`python -m sna serve --offline --open`（示例数据，虚构代码 DEMO）。

## 页面

**宏观首页 `/`**

| 卡片 | 内容 | 来源 |
|---|---|---|
| 市场概况 | 9 个主要资产 ETF 报价，12 个板块 ETF 今日涨跌 | FMP |
| 宏观数据 | 利率（联邦基金、2Y、10Y、期限利差、通胀预期）、信用利差、金融条件、VIX 和 VIX3M、美元、原油、CPI/核心 PCE 同比、失业率、非农、初请、股指收盘；每项有较上期、1 周、1 月、1 年变化和走势线 | FRED（免费） |
| 经济日历 | 前 3 天到后 10 天，默认只看美国，可只看高影响 | FMP |
| 美联储 | 货币政策新闻稿、讲话与国会证词 | 美联储官方 RSS（免费） |
| 宏观新闻 | 合并去重的新闻表格，可按来源筛选、搜索 | MarketWatch、ZeroHedge、华尔街见闻（免费），FMP |
| 期货持仓 | 标普、纳指、罗素、道指、2/10/30 年美债、VIX、美元指数期货：资产管理人和杠杆基金的净多、周变化、3 年分位 | CFTC TFF 报告（免费） |

**个股页 `/t/NVDA`**

| 卡片 | 内容 | 来源 |
|---|---|---|
| 概况 | 报价、行业、市值、52 周区间、均线、外部链接 | FMP，SEC |
| 个股新闻 | 3/7/14/30 天的新闻表格，多来源合并去重；按来源、类型、Massive 情绪筛选；“只看标题提到 NVDA”去掉顺带提到的文章；点一行展开摘要和情绪理由 | Massive、FMP、Seeking Alpha、Nasdaq（免费），Finnhub、Alpaca（可选），GDELT（免费，默认隐藏） |
| 内部人交易 | 近 90 天 Form 4：公开市场买入/卖出金额和人数、10b5-1 计划卖出占比、逐笔明细 | SEC EDGAR（免费） |
| 大股东与公司文件 | 13D/13G（谁申报、主动还是被动），8-K 重大事件（按 Item 翻成中文），144 拟出售、S-3/424B 增发、10-Q/10-K | SEC EDGAR（免费） |
| 分析师评级 | 目标价共识和评级变动 | FMP |

**数据源页 `/status`**：哪些 key 已设置（只显示是/否）、本次启动后每个来源的结果和耗时、本地缓存大小。

## 命令行

```
python -m sna serve [--port 8790] [--open] [--offline]
python -m sna doctor [--symbol NVDA]        实测所有来源，核对 FMP 时间基准，结果存 data/settings.json
python -m sna news NVDA [--days 7] [--json] 在终端看合并后的新闻（--json 给脚本或 Claude 用）
python -m sna status                        哪些 key 已设置、缓存大小
python -m sna clear-cache                   清掉缓存的响应（新闻历史保留）
```

## 数据源和核实情况

2026-11-07 在你电脑上用 `python -m sna doctor --symbol NVDA` 逐个实测过（Alpaca 没设 key，没测）。数字是那次 NVDA 的结果；以后想确认，再跑一次 `doctor` 就行。

| 来源 | 用在哪 | 需要 | 状态 |
|---|---|---|---|
| Massive `/v2/reference/news` | 个股新闻和情绪 | `MASSIVE_API_KEY`（免费档每分钟 5 次） | 实测：NVDA 7 天约 170 条，带 insights |
| FMP stable | 新闻、综合新闻、报价、公司资料、评级、目标价、经济日历 | `FMP_API_KEY` | 实测。你的套餐不含 `news/press-releases` 和 `batch-quote`（HTTP 402）：新闻稿显示“跳过”，报价改成逐个请求（21 次，缓存 5 分钟）。新闻时间是美东、日历时间是 UTC |
| SEC EDGAR | Form 4、13D/13G、8-K、144、增发 | `SEC_USER_AGENT` | 实测：代码表、Form 4、文件列表都正常 |
| FRED `fredgraph.csv` | 宏观数据 | 无（可选 `FRED_API_KEY`） | 实测：22 个序列都取到 |
| CFTC Socrata `gpe5-46if` | 期货持仓 | 无 | 实测：9 个合约都取到 |
| 美联储 RSS | 美联储卡片 | 无 | 实测：两个 feed 各 15 条 |
| MarketWatch、ZeroHedge RSS | 宏观新闻 | 无 | 实测 |
| 华尔街见闻 `api-one.wallstcn.com` | 宏观新闻（中文快讯） | 无 | 实测 |
| Seeking Alpha、Nasdaq RSS | 个股新闻 | 无 | 实测。Seeking Alpha 的 feed 限个人非商业使用；Nasdaq 的 feed 有时一个月不更新 |
| GDELT DOC 2.0 | 个股全网报道 | 无（每 5 秒 1 次） | 实测过，但经常返回 HTTP 429（GDELT 自己限流），这时用缓存；默认隐藏（噪音多） |
| Finnhub、Alpaca | 个股新闻 | 可选免费账户 | Finnhub 实测（NVDA 7 天 250 条）；Alpaca 未实测 |

没有接的：Yahoo Finance 和 Google News 的 RSS（robots.txt 不允许自动抓取）、CNBC（抓取被拒）、Barchart（服务条款禁止抓取）、Reddit（需要申请 API，下一步再说）、期权（用你的 cboe 项目）。13F 按个股汇总没有可靠的免费接口，本版只显示下一次 13F 截止日和 WhaleWisdom 链接。

## 本地文件

- `data/cache.sqlite`：抓到的原始响应。报价 5 分钟，新闻 15 分钟，经济日历、美联储和 SEC 文件列表 30 分钟，FRED 3 小时，CFTC 6 小时，SEC 单份文件 30 天（文件不会变）。来源出错时先用旧缓存，并在卡片上标出。
- `data/news.sqlite`：每条新闻第一次被本机抓到的时间（以后做回测或接 ifp 时用，现在不影响页面）。
- `data/settings.json`：`doctor` 测到的事实（FMP 时间基准），不含 key。
- `data/` 整个不进 git。

## 安全

- key 只从环境变量读（Windows 上还会读用户环境变量，新加的 key 不用重开终端）；不写进任何文件、缓存或日志，出错信息里出现的 key 会被替换成 `***`。Massive、Finnhub、Alpaca 的 key 放在请求头里，不进网址。
- 服务只监听 127.0.0.1，检查 Host 头（防 DNS rebinding），只读（没有写接口），页面有 CSP。
- 外部文字（标题、摘要、人名）只当纯文本显示，只有 http/https 链接可以点。

## 测试

```
python -m unittest discover -s tests
```

离线跑，不需要网络和 key：解析（RSS/Atom、Form 4、FRED CSV、CFTC）、时间（美东夏令时、RFC 822、FMP、GDELT）、去重、key 不外泄，以及整个网页服务的每个接口。

## 文件结构

```
sna/            Python 包：config、netio（缓存和请求）、timeutil、textutil、news（合并去重）、macro、ticker、web、fixtures
sna/sources/    每个来源一个适配器：massive、fmp、sec、rss、fred、cftc、other_news（华尔街见闻、GDELT、Finnhub、Alpaca）
ui/             app.html、app.css、app.js
config/         feeds.json：RSS 地址、ETF 列表、FRED 序列、CFTC 合约代码，可以直接改
tests/          单元测试、网页测试和离线示例数据（fixtures/http）
ARCHITECTURE.md 设计文档（v0.2：现在只做抓取；AI 标签和接入 ifp 是以后的阶段）
```

只供个人研究，不构成投资建议。
