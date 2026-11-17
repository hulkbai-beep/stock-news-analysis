# Stock News Analysis：架构与契约草案 v0.2

> 状态：v0.2（2026-11-07）。现在只做抓取和本地网页，见第 0 节；第 1 节以后是以后阶段（AI 标签、三类资金视角、接入 investment-final-plan）的设计，暂缓。
> 更新：2026-11-07
> 范围：收集个股新闻、宏观新闻和机构行为数据（SEC 申报、CFTC 持仓），用 AI 把每条新闻变成结构化标签，导出带版本的 `news-1.0` 契约。investment-final-plan 读这份契约，在网页和 AI 交易计划里当参考。
>
> 本系统是个人决策辅助工具，不构成投资建议。

---

## 0. v0.2：现在只做抓取和本地网页（2026-11-07 Tim 调整）

- **先不接入 investment-final-plan。** 先做独立的本地网页：首页显示宏观数据和宏观新闻；输入股票代码，看这只股票的新闻表格和机构行为。
- **这个 skill 只做新闻抓取。** 不做 AI 打标签、不打分；唯一的情绪是 Massive 随新闻附带的 `insights`，原样显示并注明来源。下面第 6、7、9 到 11 节（AI 标签、三类资金视角、`news-1.0` 契约、接入 ifp、评估）暂缓，等 Tim 要再做。
- **尽量免费。** FRED、美联储 RSS、CFTC、SEC EDGAR、MarketWatch、ZeroHedge、Seeking Alpha、Nasdaq、华尔街见闻、GDELT 都免费；Massive 免费档可用；FMP 用现有套餐；Finnhub、Alpaca 是可选的免费账户。
- **代码。** `sna/`（标准库 Python，来源适配器在 `sna/sources/`），`ui/`（原生 HTML/JS/CSS），`config/feeds.json`（来源清单），`tests/`（离线示例数据和测试）。运行方式、页面内容和每个来源的核实情况见 README。
- **已实测（2026-11-07，用 Tim 的 key）。** Massive 新闻用 `Authorization: Bearer` 头，NVDA 7 天约 170 条。FMP 新闻时间是美东（12 篇同时在 Massive 的文章都差整 5 小时），经济日历是 UTC（8:30 ET 的非农写成 13:30）。Tim 的 FMP 套餐不含 `news/press-releases` 和 `batch-quote`（HTTP 402），所以新闻稿跳过、报价逐个请求。
- **保留的原则。** 第 1 节的时间点一致（每条新闻记第一次抓到的时间，存在 `data/news.sqlite`）、免费优先、只存标题摘要链接、不抓服务条款禁止的网站，现在就照做。

## 1. 设计原则

1. **第三个分析层，只给事实和标签。** 和 `fmp-fundamental-analysis`、`fmp-technical-analysis` 平级。标签是"测量"：这条新闻说了什么、对公司未来的现金流或风险是正是负、是不是新信息、影响多久。它不回答"该不该买"，权重、打分和怎么用都归决策层。
2. **数字由代码算，LLM 只做两件事。** 一是给新闻打标签（结构化输出，每个标签都要引用原文，代码核对引用确实出自原文）；二是在决策层写解读（三类资金反应、每日简报），解读里的数字逐个核对。
3. **每个视角都落在可观测的数据上。** 三类资金视角不让模型凭空想象资金会怎么想：CTA 的判断全部由代码从量价算出；对冲基金和共同基金的视角，模型只能引用契约里的事实。
4. **时间点一致。** 每条记录同时存发布时间（`published_utc`）和我们拿到的时间（`fetched_utc`），回测只用当时已经拿到的数据。
5. **可复现。** 标签按（Story、股票、prompt 版本、模型）缓存，重跑不花钱、结果不变。契约带版本号，字段只增不改，改名或删除就升主版本。
6. **免费优先，合规优先。** 商业媒体只存标题、摘要、链接和我们自己的标签；SEC、美联储、CFTC 的公开文件可以存全文；不抓服务条款禁止抓取的网页。
7. **第 1 阶段不影响计划。** 新闻契约不进 plan 的 `inputs`，`plan_id` 不变，`tools/replay.py` 的回放结果逐字节不变。

## 2. 已确定的决策

| # | 问题 | 决定 |
|---|---|---|
| 1 | 新闻在计划里的角色 | 第 1 阶段只做参考：进网页和 AI 交易计划，规则计划不变。攒 4 到 8 周数据、做完评估（第 11 节）之后，再决定第 2 阶段的闸门（2026-11-07 Tim 选定） |
| 2 | 放在哪里 | 独立的第三个 skill，本地文件夹 `C:\Users\Tim\Documents\claude\stock-news-analysis`，导出 `news-1.0` 契约。investment-final-plan 只读契约，不读这里的数据库 |
| 3 | 数据源分类 | 按 Tim 的矩阵分成两类：新闻流（个股和宏观新闻），机构行为（SEC 申报、CFTC 持仓、散户和期权情绪） |
| 4 | 分析视角 | 加对冲基金、共同基金、CTA 三类资金视角（Tim 的建议），每个视角都落在可观测的数据上（第 7 节） |
| 5 | 实时流 | 暂不做 WebSocket。计划周期是 swing（约 10 个交易日）和 position（约 60 个交易日），又是手动下单，一天拉几次就够。第 5 阶段做持仓提醒时再接 |
| 6 | 覆盖范围 | 先覆盖 `data/runs` 里的 10 只：AMD、AMZN、AVGO、GOOG、META、MSFT、NFLX、NVDA、TSLA、TSM，加上宏观。以后选股漏斗要扩到更多股票时，成本大致按股票数线性增长 |
| 7 | 技术栈 | 和 investment-final-plan 一致：Python 3.11+，以标准库为主；LLM 用官方 `anthropic` SDK；存储用一个 SQLite 文件 |
| 8 | 语言 | 数据库和契约统一存英文。中文新闻（华尔街见闻）由模型直接读，标签照样是英文；界面沿用 investment-final-plan 的做法显示中文 |

## 3. 系统架构

```
数据源：新闻流 · 机构行为 · 宏观数据 · 行情
   │
   ▼  ① 拉取（Ingest）：每个来源一个适配器，统一成 Article，记 published_utc 和 fetched_utc
news.sqlite（只属于本 skill）
   │
   ├─ ② 合并（Cluster）：URL 规范化 + 标题相似度，同一件事合并成一个 Story，转载家数记为关注度
   ├─ ③ 打标签（Label）：Haiku 5.5 批处理 + 结构化输出，按 (Story, 股票, prompt, 模型) 缓存
   ├─ ④ 补充（Enrich）：SEC 8-K item 直接映射事件类型；新闻日的价格反应（相对 SPY 和板块 ETF）
   ├─ ⑤ 持仓（Positioning）：Form 4、13D/G、13F，能拿到时加 short interest 和期权指标
   └─ ⑥ 宏观（Macro）：主题标签、数据 surprise、美联储措辞变化、市场隐含情绪、CFTC 持仓
   │
   ▼
news-1.0 契约（每只股票一份，内嵌当天的宏观快照）
   │
   ▼
investment-final-plan
   · runner 把 news_contract.json 和 FA / TA 契约放在同一个运行目录
   · ifp/news_view.py：情绪视图（加权、衰减、z 分、关注度、背离）和 CTA 触发图，参数在规则文件的 [news] 表
   · 三类资金反应（重大事件，Sonnet 5.5，同时读 FA、TA、新闻）和每日简报（Opus 5.5），数字过 Validator
   · 网页："新闻与情绪" tab、首页"市场情绪"卡片、简报页；AI 交易计划（ai-plan-1.3）多读新闻
   · 第 1 阶段规则不读新闻，plan_id 不变
```

**三类资金反应为什么放在引擎里、不放进契约：** 它要同时读 FA、TA 和新闻三份契约，而每个 skill 只知道自己的数据。这和"AI 交易计划"一样，属于决策层的解释。

### 仓库分工

| 仓库 | 负责 |
|---|---|
| `stock-news-analysis` | 拉取、合并、打标签、价格反应、持仓数据、宏观快照；导出 `news-1.0` 契约和 JSON Schema；离线测试 |
| `investment-final-plan` | 读契约；情绪视图和 CTA 触发图；三类资金反应和每日简报；网页；AI 交易计划；第 2 阶段起的闸门规则 |

## 4. 数据源

额度和限制都按 2026-11-07 查到的官方文档；标"待验证"的要拿到 key 后用真实请求确认。

### 4.1 新闻流

| 来源 | 内容 | 免费额度和限制 | 用法 |
|---|---|---|---|
| Massive `GET /v2/reference/news` | 个股新闻：标题、摘要、发布方、tickers、keywords；`insights` 里有 Massive 自己用 LLM 给每只股票打的 positive / neutral / negative 和一句理由（2024-07-02 起） | 所有 Stocks 套餐都包含；免费的 Stocks Basic 有 2 年历史，Starter（$29/月）起是全部历史。每小时更新，发布方的延迟从不到 1 小时到几个小时；没有"收到时间"字段 | 个股主力。`insights` 当免费基线，和我们的标签对照（第 11 节） |
| Alpaca `GET /v1beta1/news` | Benzinga 新闻，2015 年起，带全文（`content`，可能是 HTML 或空）和摘要；另有 WebSocket | 现在的文档没写免费账户能不能用、限速多少（2022 年上线时免费，每分钟 200 次）。**待验证：需要 Tim 注册免费账户** | 如果免费可用，作为第二个主力，也就不用买 Massive 的 Benzinga 数据（$99/月/数据集） |
| FMP | `news/stock?symbols=`、`news/press-releases?symbols=`（公司公告）、`news/general-latest`（宏观和市场新闻）、`grades-historical`（评级变动）、`price-target-consensus` | Basic 免费每天 250 次；Starter 起写明包含 "Financial Market News"，各档的新闻覆盖范围文档没写清。**待确认 Tim 的套餐** | 补充。公告和评级变动直接对应事件类型 |
| Finnhub `company-news`、`news` | 个股和市场新闻 | 免费额度没能从官网核实（页面是 JS 渲染的）。**待验证** | 备选 |
| RSS：Seeking Alpha（个股）、ZeroHedge、华尔街见闻、CNBC、公司 IR、PR Newswire / GlobeNewswire / Business Wire | 标题、摘要、链接 | 免费；各家服务条款不同，只存标题、摘要和链接，自用 | 分别处理：ZeroHedge 偏空又耸动，只当"叙事热度"、权重压低；Seeking Alpha 大多是观点文，标成 opinion；华尔街见闻是中文，模型直接读 |
| GDELT DOC 2.0 | 全球新闻按关键词的报道量和语气（TimelineVol、TimelineTone） | 免费；默认只回看最近 3 个月，一次最多 250 条结果 | 宏观和地缘主题（关税、出口管制、台海、制裁）。BigQuery 版只用于一次性回填 |
| Tiingo | 新闻 | 免费档只限内部使用，新闻没有历史；3 个月历史要 Power（$30/月） | **不用** |

### 4.2 机构行为

| 来源 | 内容 | 时效 | 用法 |
|---|---|---|---|
| SEC EDGAR `data.sec.gov/submissions/CIK##########.json` | 公司所有申报的列表 | 实时更新；不需要 key；每秒最多 10 次，请求头要写 User-Agent（联系方式）。返回字段名动手前用真实请求核对 | 8-K 事件（第 6.2 节）、Form 4、13D/G、S-3 / 424B 增发 |
| Form 4 | 内部人买卖 | 交易后 2 个工作日内申报；表上有是否按 10b5-1 计划交易的勾选项 | 近 90 天净买卖。按计划卖出的信息量低，单独统计；高管在公开市场集体买入是强信号 |
| Schedule 13D / 13G | 持股超过 5% | 13D：超过 5% 后 5 个工作日内申报，修订在 2 个工作日内。13G：被动投资者 5 个工作日内；机构投资者在季度结束后 45 天内 | 激进投资者（13D）当事件用；13G 只看持股结构 |
| Form 13F | 管理资产超过 1 亿美元的机构的季度持仓 | 季度结束后 45 天内申报，所以看到的是 2 到 4 个月前的持仓。下一批（2026 年三季度）截止日是 2026-11-16 | 只看持仓结构和拥挤度（对冲基金的持股集中度、长线机构的季度增减），**不能拿来择时** |
| CFTC COT（TFF 报告） | 期货持仓，分 Dealer / Intermediary、Asset Manager / Institutional、Leveraged Funds、Other Reportables | 每周二收盘时的持仓，周五 15:30 ET 公布；`publicreporting.cftc.gov` 有免费 API，正常使用不需要 token | 指数和利率层面的拥挤度：ES、NQ、国债期货里 Leveraged Funds（对冲基金和 CTA）和 Asset Manager（长线机构）的净头寸，在过去 3 年里的分位。股指统一用 TFF 报告，不和 Legacy 报告的 Non-Commercial 混用 |
| Reddit（r/wallstreetbets、r/stocks、r/investing） | 散户讨论 | 需要注册 Reddit 应用，个人非商业用途 | 可选：提及次数的 z 分，极端时当反向指标 |
| 期权（Tim 的 cboe 期权项目） | put/call、IV skew、gamma | 取决于那边的数据 | 拥挤度和轧空风险。不抓 Barchart 网页（服务条款风险，页面一改就坏） |
| Short interest（FINRA） | 空头仓位 | 每月公布两次 | 轧空风险；获取方式待核实 |

### 4.3 宏观数据和行情

| 来源 | 内容 | 用法 |
|---|---|---|
| 美联储 RSS | `press_monetary.xml`（货币政策声明）、`speeches.xml`、`speeches_and_testimony.xml`、`prates.xml` | 声明和讲话原文；措辞和上一次对比（第 8 节） |
| FMP `economic-calendar` | 经济数据发布（技术面 skill 已经用它排宏观日程） | 已发布数据的实际值、预期值和前值，用来算 surprise；字段名动手前用真实请求核对 |
| FRED | `VIXCLS`、`VXVCLS`（3 个月 VIX）、`BAMLH0A0HYM2`（高收益债利差）、`DGS2`、`DGS10`、`T10Y2Y`、`NFCI` | 市场隐含情绪。`series/vintagedates`（ALFRED）给出数据当时的版本，回测不会用到事后修订的数 |
| Massive 或 FMP 日线 | 10 只股票、SPY 和对应板块 ETF 的日线 | 新闻日的价格反应 |

**API key 一律放环境变量**，和现有两个 skill 一样，不写进代码，也不贴进对话：`MASSIVE_API_KEY`（变量名待确认）、`FMP_API_KEY`、`ALPACA_API_KEY_ID` 和 `ALPACA_API_SECRET_KEY`、`FRED_API_KEY`、`ANTHROPIC_API_KEY`，可选的 `REDDIT_CLIENT_ID` 和 `REDDIT_CLIENT_SECRET`。SEC 要求的联系方式放在 `SEC_USER_AGENT`。

## 5. 合并与时间

### 5.1 同一件事只算一次

1. URL 规范化：去掉 `utm_*` 之类的追踪参数、AMP 后缀和末尾斜杠。
2. 标题规范化：小写，去标点，去掉发布方后缀（如 " - Reuters"），再切成词。
3. 48 小时内、涉及的股票有交集、标题词集合的 Jaccard 相似度 ≥ 0.6 的文章，归为同一个 Story。
4. Story 记最早的发布时间和最早的拿到时间、所有发布方、转载家数（`n_articles`）。转载家数就是关注度的原始数据。
5. SEC 申报和公司公告各自单独成 Story（`kind` 不同）。如果某条新闻报道的就是这份公告，标签里记 `related_story`，不重复计分。

### 5.2 归到哪个交易日

按 NYSE 交易日历（和技术面 skill 一致）：

| 拿到的时间（美东） | `session.when` | 价格反应看哪天 |
|---|---|---|
| 交易日 9:30 之前 | `pre_market` | 当天 |
| 9:30 到 16:00 | `intraday` | 当天 |
| 16:00 之后、周末、假日 | `post_market` | 下一个交易日 |

实时运行用 `fetched_utc`。回填历史时没有拿到的时间，用 `published_utc` 加 2 小时当作"可以拿到的时间"（Massive 每小时更新一次，再加上发布方的延迟），偏保守。

## 6. AI 打标签

### 6.1 每个 Story 的标签（`news-label-1.0`）

| 字段 | 取值 | 说明 |
|---|---|---|
| `role` | subject / supplier / customer / competitor / peer / mention | 这只股票在新闻里的角色。只给股票池里的股票打标签，顺带提到的标 mention |
| `event_type` | 见 6.2 的事件类型表 | |
| `direction` | -2 到 +2 | 对这家公司未来现金流或风险的影响，**不是**对股价的预测 |
| `magnitude` | 1 / 2 / 3 | 重要性：1 小，2 中，3 足以改变盈利、估值或法律风险 |
| `novelty` | new_fact / update / opinion / recap | 新事实；已知事件的新进展；观点和评论；"为什么今天涨跌"一类的复盘 |
| `horizon` | days / weeks / quarters | 影响多久，对应 swing / position / long |
| `expectation` | beat / miss / inline / none / unknown | 只在原文明确和预期或一致预期比较时填，否则填 unknown |
| `thesis_impact` | `{level: none / minor / material, area}` | 是否改变 1 到 3 年的基本面逻辑；area 取 growth、margins、moat、regulation、capital_allocation、balance_sheet、management（共同基金视角用） |
| `confidence` | low / medium / high | |
| `rumor` | true / false | 未经证实的传闻 |
| `rationale` | 英文，不超过 30 个词 | 一句话理由 |
| `evidence` | 原文片段 | 必须逐字取自输入。代码核对它确实是输入的子串，不是就重试一次，仍然不是则 `confidence` 降为 low |

**Prompt 规则（`prompts/news-label-1.0.md`，英文）：**

- 只依据给出的文字判断，不用模型自己知道的、发生在发布时间之后的事。这一条对回填历史尤其重要。
- `direction` 衡量对公司基本面和风险的影响，不预测股价。原文信息不够就给 0，`confidence` 为 low。
- 复盘类（"为什么某股今天下跌"）的 `novelty` 一律是 recap，方向跟着文中给出的原因走。
- 榜单和荐股文（"3 只该买的 AI 股"）的 `novelty` 一律是 opinion。
- 一条新闻涉及多只股票时，分别打标签。
- 用结构化输出（JSON Schema），一次请求 10 个 Story，系统提示（事件类型表和规则）放在最前面缓存。

**模型：** `claude-haiku-5-5`，effort `low`。日常和回填都走 Message Batches（价格减半）；"刷新新闻"按钮需要马上出结果时走普通请求。

### 6.2 事件类型（`events-1.0`）

| `event_type` | 说明 | 能直接确定类型的来源 |
|---|---|---|
| earnings | 财报业绩 | 8-K item 2.02 |
| guidance | 业绩指引变化 | |
| analyst | 评级、目标价变动 | FMP `grades-historical` |
| product | 产品、技术、业务进展 | |
| contract | 订单、客户、合作；重大协议的签订或终止 | 8-K item 1.01、1.02 |
| m_and_a | 并购、剥离 | 8-K item 2.01 |
| capital_return | 回购、分红 | |
| financing | 增发、可转债、大额借款（稀释） | S-3、424B；8-K item 2.03、3.02 |
| restructuring | 裁员、关停、重组费用 | 8-K item 2.05 |
| accounting | 财报重述、减值、更换审计师 | 8-K item 4.02、2.06、4.01 |
| legal_regulatory | 诉讼、调查、反垄断、出口管制、退市通知 | 8-K item 3.01 |
| management | 高管、董事变动 | 8-K item 5.02 |
| supply_chain | 供应商、客户、产能 | |
| insider | 内部人交易 | Form 4 |
| ownership | 持股超过 5% 的变化 | 13D / 13G |
| short_report | 做空报告 | |
| macro_exposure | 宏观或政策对这家公司的直接影响（关税、出口管制） | |
| market_move | 复盘类 | |
| opinion | 观点、评论、榜单 | |
| other | 其他 | |

能从 SEC item 或 FMP 评级直接确定类型的，`event_type` 由代码填，模型只判断方向、重要性和其余字段。8-K 正文（包括 99.1 新闻稿）是公开文件，可以把前 2,000 个词交给模型。

### 6.3 来源级别

放在 `config/sources.toml`，没列出的发布方默认算 tier2。

| 级别 | 例子 |
|---|---|
| tier1 | SEC、美联储、公司公告；Reuters、Bloomberg、Dow Jones / WSJ、AP、CNBC |
| tier2 | 其他主流财经媒体、华尔街见闻快讯、Benzinga 新闻 |
| tier3 | 观点和内容农场类：Seeking Alpha 投稿文章、Motley Fool、Zacks、InvestorPlace、ZeroHedge |

## 7. 三类资金视角

同一条新闻，三类资金的反应截然不同（Tim 的框架）。每个视角先由代码从数据里算出"事实"，模型只在这些事实之上做解释。

| 视角 | 看什么 | 用哪些数据（谁来算） | 时间尺度 |
|---|---|---|---|
| 对冲基金 | 预期差、拥挤度、催化剂、轧空风险。利好但仓位拥挤时，容易 "Sell the news" | 预期差：标签里的 `expectation`，财报实际值对比一致预期。Whisper number 没有可靠的免费来源，所以用两个代理：财报前 20 天的涨幅（是否已经 price in），以及期权隐含的波动幅度和实际波动的对比（有期权数据时）。拥挤度：TA 的 `extension`（RSI14、z20、`dist_sma50_atr`）、13F 里对冲基金的持股集中度、short interest、期权的 put/call 和 skew。"Sell the news" 就是 10.1 节的背离信号 | 几天 |
| 共同基金 | 1 到 3 年的基本面逻辑有没有变；行业合规；估值锚；板块轮动 | 标签里的 `thesis_impact`；FA 的估值温度和业务质量（rules-1.2 写在 `context.fa.rules` 里）；板块相对强弱（TA 的 `rs.vs_sector`、`market.sector`）；13F 里长线机构的季度增减 | 几周到几个月 |
| CTA | 不看新闻内容，只看新闻引发的价格突破、均线穿越和波动率变化 | **全部由代码算**（10.2 节的 CTA 触发图）：TA 的 `trend.sma20/50/200`、`atr14`、`volatility.rv20_pctl`、`regime`；指数层面再看 COT 里 Leveraged Funds 的仓位分位和 VIX 分位 | 几天到几周 |

**三类资金反应（在引擎里生成，`prompts/news-lens-1.0.md`）：**

- 只对重大事件做：`magnitude` 为 3；或者 `magnitude` 为 2、`novelty` 为 new_fact，且新闻日相对板块的超额收益超过 1 个 ATR%。每只股票每天最多 3 条，10 只合计大约每天 5 到 15 条。
- 输入：这条 Story 和它的标签、价格反应、CTA 触发图、FA 和 TA 的相关事实、持仓数据（4.2 节）、当天的宏观状态。
- 输出（结构化，下面是示例）：

```jsonc
{
  "hedge_funds":  {"stance": "sell", "conviction": "medium", "horizon": "days",
                   "reasoning": "...", "evidence": ["ta.extension.rsi14", "news.story.label.expectation"],
                   "confirm_if": "...", "invalidate_if": "..."},
  "mutual_funds": {"stance": "no_action", "conviction": "low", "horizon": "weeks_months", "...": "..."},
  "cta":          {"stance": "reduce", "source": "engine", "...": "..."},  // 立场由代码按触发图给出，模型只解释
  "net_read": "...",
  "key_levels": [219.81, 204.67],                                           // 只能取自 TA 契约
  "uncertainties": ["..."]
}
```

- `stance` 取 buy、add、no_action、reduce、sell。CTA 的立场由代码按触发图给出（例如收盘跌破 SMA50 且 rv20 分位跳到 90 以上，记 reduce），模型只负责解释。
- Validator：正文里的每个数字都要能在输入里找到，`evidence` 里的字段路径要真实存在。不通过就重试一次，仍不通过则标记出来并显示原因。
- 模型：`claude-sonnet-5-5`，effort `medium`。每条大约 $0.05，每月约 $10。
- 结果存进 `ifp.sqlite` 的新表 `news_lenses`，每次调用照样记进 `llm_calls`。
- 以后可以直接变成"多 Agent"规范里的三个分析员，给多空辩论提供弹药。

## 8. 宏观快照

每天算一次，嵌进当天所有股票的 `news-1.0` 契约（带自己的 `id` 和 `as_of`），这样引擎看到的宏观数据和计划是同一天的。

1. **主题新闻**：FMP 市场新闻、美联储 RSS、GDELT 和 RSS 里的宏观条目，按主题打标签：`fed_policy`、`inflation`、`labor`、`growth`、`trade_tariffs`、`geopolitics`、`credit_liquidity`、`ai_capex`（对这 10 只股票最关键）、`earnings_season`。方向是对美股风险偏好的影响，从 -2（risk-off）到 +2（risk-on）。**只评价已经发生的事和已经发布的数据，不预测未来数据的结果**，和 ai-plan prompt 的规定一致。
2. **数据 surprise（代码算）**：已发布数据的（实际值 − 预期值）÷ 同一指标过去 surprise 的标准差。
3. **美联储措辞变化**：新的 FOMC 声明和上一次逐句对比，模型只读变化的句子，给出鹰鸽变化（-2 偏鹰到 +2 偏鸽），并列出变化的原句。讲话只记主题和语气，权重低于声明。
4. **市场隐含情绪（代码算）**：VIX 和它的一年分位、VIX / VIX3M（期限结构倒挂说明市场紧张）、高收益债利差和它的 20 天变化、2 年和 10 年国债收益率、2s10s、NFCI。
5. **CFTC 持仓（代码算，每周更新）**：ES、NQ、10 年国债期货里 Leveraged Funds 和 Asset Manager 的净头寸，以及它们在过去 3 年里的分位。
6. **宏观状态**：risk-on / neutral / risk-off 由引擎按规则文件的 `[news.macro]` 判断，例如 VIX 分位 ≥ 90、高收益债利差 20 天扩大超过阈值、宏观新闻净情绪 z 分 ≤ -1.5、SPY 在 200 日线下，满足其中几条。第 1 阶段只显示，不影响计划。

## 9. 契约 `news-1.0`

### 9.1 通用规则

和 FA / TA 契约一致：`as_of` 指数据截止的交易日，运行时间放 `generated_at`；缺失值用 `null`，并在 `warnings` 或对应块的 `reason` 里说明，不估算；字段只增不改；导出模块是纯函数，测试可以离线运行。

### 9.2 结构（示例，数字为虚构）

```jsonc
{
  "contract": "news-1.0",
  "ticker": "NVDA",
  "generated_at": "2026-11-07T13:05:12Z",
  "as_of": "2026-11-06",
  "cutoff_utc": "2026-11-06T21:00:00Z",          // 只用这个时间之前拿到的数据
  "versions": {"taxonomy": "events-1.0", "label_prompt": "news-label-1.0",
               "label_model": "claude-haiku-5-5", "macro_prompt": "macro-label-1.0"},
  "sources": [
    {"name": "massive_news", "ok": true, "items": 214, "fetched_at": "2026-11-07T13:01:40Z"},
    {"name": "alpaca_news", "ok": false, "reason": "ALPACA_API_KEY_ID not set"},
    {"name": "sec_submissions", "ok": true, "items": 6, "fetched_at": "2026-11-07T13:01:52Z"}
  ],
  "window": {"stories_days": 20, "daily_days": 120},
  "stories": [{
    "id": "st_20261105_7f3a",
    "kind": "news",                                 // news | press_release | sec_filing | analyst_action | insider | ownership
    "first_published_utc": "2026-11-05T12:31:00Z",
    "first_fetched_utc": "2026-11-05T13:02:44Z",
    "session": {"date": "2026-11-05", "when": "pre_market"},
    "headline": "...", "summary": "...",
    "publishers": ["Reuters", "Benzinga"], "n_articles": 7, "urls": ["https://..."],
    "source_tier": 1,
    "sec": null,                                    // 8-K 时：{"form": "8-K", "items": ["2.02", "9.01"], "accession": "..."}
    "related_story": null,
    "vendor_sentiment": {"massive": "negative"},
    "label": {"role": "subject", "event_type": "guidance", "direction": -2, "magnitude": 3,
              "novelty": "new_fact", "horizon": "quarters", "expectation": "miss",
              "thesis_impact": {"level": "material", "area": "margins"},
              "confidence": "high", "rumor": false,
              "rationale": "...", "evidence": "..."},
    "reaction": {"date": "2026-11-05", "ret": -0.041, "gap": -0.028,
                 "vs_spy": -0.032, "vs_sector": -0.025, "rvol": 2.3}
  }],
  "daily": [{
    "date": "2026-11-06", "n_stories": 12, "n_articles": 41,
    "buckets": {"new_fact|1|3": {"n": 1, "signed": -2, "abs": 2},
                "opinion|3|1": {"n": 4, "signed": 2, "abs": 4}},   // 键：新颖度|来源级别|重要性
    "related": {"n": 3, "signed": 1, "abs": 3},                   // 供应商、客户、竞争对手的新闻
    "dispersion": 1.1,
    "vendor": {"n": 10, "net": -0.3}                               // Massive insights 的平均
  }],
  "positioning": {
    "insider_90d": {"buys": 0, "sells": 14, "net_shares": -1250000, "net_value": -240000000,
                    "plan_10b5_1_share": 0.86, "officer_open_market_buys": 0},
    "beneficial_5pct": [],
    "ownership_13f": {"quarter": "2026-06-30", "lag_days": 129, "hedge_fund_share": 0.071,
                      "hedge_fund_share_qoq": 0.004, "long_only_share_qoq": -0.002},
    "short_interest": null,
    "options": null,
    "unavailable": ["short_interest", "options"]
  },
  "macro": {"id": "macro_2026-11-06", "as_of": "2026-11-06", "...": "见第 8 节"},
  "data_quality": {"daily_coverage": 120, "missing_days": [], "label_failures": 0,
                   "evidence_failures": 1, "late_items": 3, "stale": false},
  "usage": {"calls": 18, "input_tokens": 51234, "output_tokens": 20871, "est_cost_usd": 0.016},
  "warnings": [], "errors": [],
  "disclaimer": "..."
}
```

**`daily` 为什么存分桶、不存分数：** 权重（新颖度、来源级别、重要性各占多少）和衰减速度都是判断，归引擎的规则文件。skill 只按"新颖度 | 来源级别 | 重要性"分桶，存条数和方向之和，引擎套自己的权重。这样以后调权重，不用重跑 skill，也不用重新打标签。

`daily` 默认覆盖 120 个交易日，给引擎算 60 天基线留足余量；`stories` 默认只放最近 20 个交易日的明细，控制契约大小。

## 10. 接入 investment-final-plan

### 10.1 情绪视图 `ifp/news_view.py`（版本 `news-view-1.0`，参数在规则文件的 `[news]` 表）

1. **每日净情绪** N(d)：把各桶的方向之和乘上新颖度权重、来源权重和重要性权重，再加总。初始权重：新颖度 new_fact 1.0、update 0.6、opinion 0.3、recap 0.1；来源 tier1 1.0、tier2 0.7、tier3 0.3；重要性 1、2、3 分别为 0.5、1、2。`confidence` 为 low 的标签不进桶。
2. **衰减后的水平** S(d) = Σ N(d−k) × 0.5^(k/h)，半衰期 h 在 swing 用 3 个交易日，在 position 用 10 个交易日。
3. **z 分**：S(d) 和这只股票自己前 60 个交易日的 S 比较。历史不足 40 天时标记 `insufficient_history`，不给 z 分。NVDA 的新闻常年偏正面，绝对值意义不大，变化才有用。
4. **关注度 z 分**：不带符号的加权条数，同样和自己的 60 天比较。新闻量突然增加，往往比方向更有信息量。
5. **分歧度**：直接来自契约，即当天各条新闻方向的离散程度。
6. **背离**：`magnitude` ≥ 2、`novelty` 为 new_fact 或 update、`direction` 不为 0，而新闻日相对板块的超额收益方向相反、幅度超过 0.5 个 ATR% 时，标 `bullish_news_price_down` 或 `bearish_news_price_up`。前者就是 Tim 说的 "Sell the news"。
7. **和 Massive 的一致率**：Massive `insights` 的方向和我们标签方向相同的比例，用来监控标签质量。

### 10.2 CTA 触发图（代码，在引擎里算）

读 TA 契约，再加上新闻契约里的价格反应：

- 收盘价离 SMA20、SMA50、SMA200 和最近的支撑阻力区各有几个 ATR；
- 新闻日的跳空或收盘有没有穿过这些位置（`crossed`）；
- `volatility.rv20_pctl` 有没有跳到高位（波动率目标基金和风险平价基金被迫降仓的风险）；
- 大盘：SPY 相对 200 日线、VIX 分位、COT 里 Leveraged Funds 的仓位分位。

按规则给出 CTA 的立场（例如跌破 SMA50 且 rv20 分位 ≥ 90 记 reduce），第 1 阶段只显示。

### 10.3 运行方式

- `python -m ifp plan NVDA`：新闻 skill 已安装时顺带生成 `news_contract.json`，和 FA / TA 放在同一个 `data/runs/<代码>/<日期>/`。新闻这一步失败不影响出计划（第 1 阶段它只是参考）；`--no-news` 可以跳过。
- `python -m ifp status` 和设置页显示新闻 skill 的版本、各数据源的 key 是否设置（只显示 set / not set）、最近一次拉取时间、待打标签的数量。
- 网页加"刷新新闻"按钮：拉取、打标签（走普通请求，马上出结果）、生成契约。
- 第 1 阶段新闻契约不进 plan 的 `inputs`，`plan_id` 和回放结果不变；到第 2 阶段规则开始读它时，才进 `inputs`。

### 10.4 网页

- **个股页新增"新闻与情绪" tab**：顶部是 5 日和 20 日情绪 z 分、关注度 z 分、分歧度、背离提示、和 Massive 的一致率；中间是 120 天的价格、每日情绪柱和关注度线（复用 `chart.js`）；下面按天列出 Story，带事件类型、方向、重要性、新颖度、周期这几个标签，标题原文和链接，以及一句理由（中文显示时用现有的便宜模型翻译一次并缓存）。重大事件可以展开看三类资金反应；旁边是持仓面板（内部人 90 天、13D/G、13F）。
- **首页"市场情绪"卡片**：宏观状态和驱动因素、各主题的方向和变化、最近的数据 surprise、美联储措辞变化、VIX 和期限结构、高收益债利差、COT 的极端仓位。
- **每日简报页**：Opus 5.5 每天写一份（按按钮生成），宏观一段，再加每只股票的多空要点。每句话引用 Story 编号，数字过 Validator，英文存库、中文显示。
- **术语表**补充：关注度 z 分、新颖度、背离、TFF、Leveraged Funds、13F 的滞后、10b5-1 等。

### 10.5 AI 交易计划（`ai-plan-1.3`）

多读两份文档：`<news_contract>`（最近 20 天的 Story、持仓数据、宏观快照）和 `<news_view>`（引擎算的情绪视图、CTA 触发图、当天的三类资金反应）。Prompt 增加以下规则：

- 新闻和情绪只是参考，可以写进风险、观察清单和持仓管理，引用时写 Story 编号；
- 不能因为新闻改动 `status = triggered` 的闸门，不同意时写进 `vs_rules.differences`；
- 不预测宏观数据的结果；
- 新闻里的数字同样要能在输入里找到。

## 11. 第 1 阶段的评估（4 到 8 周）

第 1 阶段要回答的就是"新闻情绪到底有没有用、该怎么用"。评估结果写进 `docs/eval-news-1.0.md`，再据此决定第 2 阶段。

1. **标签质量**
   - 人工核对 100 个 Story（按事件类型分层抽样）。网页上加一个"核对"模式，逐条点对错、改方向。建议的目标：new_fact 类的方向符号准确率不低于 85%。
   - 和 Massive `insights` 的一致率，按事件类型分开看。
   - `evidence` 核对的失败率。
2. **有没有预测力（事件研究）**
   - 回填：用 Massive 免费的 2 年历史（`insights` 从 2024-07 起有）给 10 只股票补标签，同时算出 60 天基线。大约 5 万个 Story，Haiku 批处理约 $5 到 $10。
   - 按情绪 z 分和关注度 z 分分组，看之后 1、5、20 个交易日相对板块 ETF 的超额收益。
   - 按事件类型看事件后第 0 天、第 1 到 5 天、第 6 到 20 天的平均超额收益（下调指引、评级下调、8-K 4.02、CEO 离职、13D、内部人集体买入等）。
   - 背离信号："利好却下跌"之后的走势，和"利好且上涨"对比。
   - 宏观状态：不同状态下 SPY 之后的收益和波动。
   - **偏差提醒**：回填结果有两处偏乐观。一是"可以拿到的时间"是估出来的；二是模型可能知道后来发生的事，打标签时带着后见之明。所以回填结果只当参考，干净的检验是第 1 阶段之后实时收集的 4 到 8 周。
3. **闸门模拟**：给 `tools/replay.py` 加 `--news`，用候选闸门（重大利空后不新开仓、宏观 risk-off 时单笔风险减半）回放存下的计划，列出哪些动作会变，再用 20 / 60 天对账看变了之后是好是坏。

## 12. 存储

`stock-news-analysis/data/news.sqlite`（不进 git，`SNA_DATA_DIR` 可以改位置），只属于本 skill，引擎只读契约。

```sql
CREATE TABLE articles (id TEXT PRIMARY KEY, source TEXT, source_id TEXT, url TEXT, canonical_url TEXT,
  title TEXT, summary TEXT, publisher TEXT, author TEXT, lang TEXT,
  published_utc TEXT, fetched_utc TEXT NOT NULL, tickers TEXT, keywords TEXT,
  vendor_sentiment TEXT, story_id TEXT, raw TEXT);
CREATE TABLE stories (id TEXT PRIMARY KEY, kind TEXT, first_published_utc TEXT, first_fetched_utc TEXT,
  session_date TEXT, session_when TEXT, headline TEXT, summary TEXT, publishers TEXT, n_articles INTEGER,
  tickers TEXT, source_tier INTEGER, sec TEXT, related_story TEXT);
CREATE TABLE labels (story_id TEXT, ticker TEXT, prompt TEXT, model TEXT, label TEXT, ok INTEGER,
  error TEXT, created_at TEXT, PRIMARY KEY (story_id, ticker, prompt, model));
CREATE TABLE reactions (story_id TEXT, ticker TEXT, date TEXT, ret REAL, gap REAL, vs_spy REAL,
  vs_sector REAL, rvol REAL, PRIMARY KEY (story_id, ticker));
CREATE TABLE bars (ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (ticker, date));
CREATE TABLE insider_tx (accession TEXT, ticker TEXT, filer TEXT, role TEXT, tx_date TEXT, code TEXT,
  shares REAL, price REAL, value REAL, plan_10b5_1 INTEGER, filed_utc TEXT, fetched_utc TEXT);
CREATE TABLE ownership_events (accession TEXT PRIMARY KEY, ticker TEXT, filer TEXT, form TEXT,
  event_date TEXT, pct REAL, filed_utc TEXT, fetched_utc TEXT);
CREATE TABLE holdings_13f (quarter TEXT, filer_cik TEXT, filer_name TEXT, filer_type TEXT, ticker TEXT,
  shares REAL, value REAL, filed_date TEXT, PRIMARY KEY (quarter, filer_cik, ticker));
CREATE TABLE macro_items (id TEXT PRIMARY KEY, source TEXT, theme TEXT, title TEXT, summary TEXT, url TEXT,
  published_utc TEXT, fetched_utc TEXT, label TEXT);
CREATE TABLE macro_releases (event TEXT, country TEXT, release_utc TEXT, actual REAL, estimate REAL,
  previous REAL, impact TEXT, fetched_utc TEXT, PRIMARY KEY (event, country, release_utc));
CREATE TABLE fed_docs (id TEXT PRIMARY KEY, type TEXT, date TEXT, title TEXT, url TEXT, text TEXT, shift TEXT);
CREATE TABLE market_series (series TEXT, date TEXT, value REAL, vintage TEXT, PRIMARY KEY (series, date, vintage));
CREATE TABLE cot (market TEXT, report_date TEXT, released_utc TEXT, category TEXT, long REAL, short REAL,
  PRIMARY KEY (market, report_date, category));
CREATE TABLE fetch_log (source TEXT, scope TEXT, from_utc TEXT, to_utc TEXT, fetched_utc TEXT,
  n INTEGER, status TEXT, error TEXT);
CREATE TABLE llm_usage (created_at TEXT, purpose TEXT, model TEXT, batch INTEGER, input_tokens INTEGER,
  cached_input_tokens INTEGER, output_tokens INTEGER, est_cost_usd REAL);
```

13F 还需要两份配置：10 只股票的 CUSIP，以及机构类型（对冲基金、共同基金、指数基金、养老金等）。SEC 不提供机构分类，所以先手工维护持仓最大的约 200 家机构的类型，其余记为 unknown。

引擎侧（`ifp.sqlite`）新增 `news_lenses`（三类资金反应）和 `news_briefs`（每日简报）两张表，LLM 用量照样记进 `llm_calls`。skill 打标签的用量写在契约的 `usage` 里，runner 也把它记进 `llm_calls`（`purpose` 记为 news_label）。

## 13. 命令行

```
python -m sna status                      # 各数据源的 key 是否设置、最近一次拉取、待打标签数量、近 30 天费用
python -m sna fetch [--tickers NVDA,AMD]  # 增量拉取所有来源
python -m sna label [--sync]              # 给新 Story 打标签，默认走批处理
python -m sna macro                       # 生成当天的宏观快照
python -m sna contract NVDA --out <路径>   # 导出 news-1.0 契约
python -m sna backfill --days 730         # 回填：Massive 新闻、FMP 评级、SEC 申报、FRED、CFTC
```

**每天的数据收集：** 你定过暂不做定时任务，计划刷新仍然手动。但第 1 阶段要攒 4 到 8 周连续的数据，漏掉的日子事后没法补回"当时拿到的时间"。建议只给数据收集加一个 Windows 任务计划（每个交易日美东 7:30 和 17:30 各跑一次 `fetch` 和 `label`），计划本身不自动刷新。这一条待 Tim 确认。

## 14. 成本估算（2026-11 的标价）

| 项目 | 量 | 模型 | 每月 |
|---|---|---|---|
| 打标签 | 每天几百个 Story（10 只股票加宏观） | Haiku 5.5（每百万 token 输入 $0.10、输出 $0.50），批处理再减半 | 不到 $2 |
| 三类资金反应 | 每天 5 到 15 条 | Sonnet 5.5（$2 / $10） | 约 $10 |
| 每日简报 | 每天 1 份 | Opus 5.5（$4 / $20） | 约 $8 |
| 回填 2 年 | 约 5 万个 Story，一次性 | Haiku 5.5 批处理 | 一次约 $5 到 $10 |
| 数据 | Massive Basic、FMP、SEC、美联储、FRED、CFTC、GDELT、RSS | | 免费档起步 |

## 15. 测试

- 离线测试用合成数据：假的新闻 JSON、假的 SEC submissions、假的 RSS，不提交真实的付费数据。
- 合并：同一事件的多篇转载必须归成一个 Story，不同事件不能被误合并。
- 交易日归属：盘前、盘中、盘后、周末、假日都要覆盖。
- 打标签：用假的 LLM 客户端返回固定 JSON，测 Schema 校验、`evidence` 子串核对、缓存命中和重试。
- 契约：`schemas/news-1.0.schema.json`，每次导出都校验。
- 引擎：news_view 的加权、衰减、z 分、背离用固定数据测；加入新闻之后，`tools/replay.py` 对存下的运行，结果逐字节不变。

## 16. 路线图

| 步骤 | 内容 |
|---|---|
| 1.1 拉取和存储 | Massive、FMP（新闻、公告、评级）、SEC（8-K、Form 4、13D/G）、日线、RSS；合并和交易日归属；离线测试 |
| 1.2 打标签 | `events-1.0`、`news-label-1.0`、结构化输出、批处理、`evidence` 核对、缓存；100 个 Story 的核对集 |
| 1.3 契约 | `news-1.0` 和 JSON Schema、`sna contract`；回填 2 年 |
| 1.4 宏观 | 美联储 RSS 和措辞变化、FMP 经济日历 surprise、FRED、CFTC TFF、GDELT 主题 |
| 1.5 接入引擎 | `news_view`、CTA 触发图、三类资金反应、每日简报、网页 tab 和首页卡片、`ai-plan-1.3` |
| 1.6 持仓补全 | 13F（季度持仓和机构类型表）；能拿到时加 short interest 和期权指标；Alpaca（Tim 注册之后）；Reddit（可选） |
| 1.7 评估 | 实时收集 4 到 8 周，写 `docs/eval-news-1.0.md`，决定第 2 阶段 |

## 17. 待确认

1. FMP 和 Massive 各是什么套餐。这决定 FMP 的新闻和公告能拿多少，以及 Massive 有没有全部历史。
2. 注册免费的 Alpaca 账户，key 放进环境变量，用来验证免费额度。
3. 数据收集要不要加 Windows 任务计划（只收集数据，不刷新计划）。
4. 要不要在 GitHub 上建 `stock-news-analysis` 仓库。需要 Tim 在 GitHub 上新建，建好之后我来接上。
5. 华尔街见闻、ZeroHedge 等 RSS 只存标题、摘要和链接，自用，这样是否可以接受。

## 18. Backlog（第 2 阶段以后）

| 项目 | 说明 |
|---|---|
| 新闻和宏观闸门 | 评估之后再定：重大利空后不新开仓或只建第 1 批；宏观 risk-off 时单笔风险减半。正好对应 investment-final-plan backlog 里的"宏观事件闸门" |
| 情绪进矩阵 | 只有评估证明有预测力，才让情绪进入 FA × TA 矩阵 |
| 实时流 | 第 5 阶段做持仓提醒时，接 Alpaca 或 Massive 的实时新闻 |
| 电话会纪要 | FMP 只有 Ultimate 才有；有了以后可以分析管理层语气的变化 |
| 多 Agent 辩论 | 三类资金反应作为三个分析员，给多空辩论提供弹药 |
| 扩大股票池 | 选股漏斗用到时扩到更多股票；先用代码过滤，只给重要的新闻打标签 |
