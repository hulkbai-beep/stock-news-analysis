---
name: stock-news-analysis
description: Fetch free macro data, macro news, one US ticker's news (merged and de-duplicated, with Massive's own sentiment tags) and its institutional behaviour (SEC Form 4 insider trades, 13D/13G holders, 8-K events, Form 144, offerings, analyst grades, CFTC futures positioning), and show them in a local web page. Use when the user asks for stock news, macro news or data, insider trades, 13D/13G filings or CFTC positioning, including Chinese requests such as 新闻, 宏观, 个股新闻, 内部人交易, 机构行为, 持仓报告. Fetch and display only; it does not score or label news itself.
---

# stock-news-analysis

Fetch-only. Do not add sentiment or bullish/bearish judgements of your own to what this tool returns; the only
sentiment it carries is Massive's `insights`, and it should be presented as Massive's.

## Run

From the project folder (`C:\Users\Tim\Documents\claude\stock-news-analysis` on Tim's machine):

- Page: `python -m sna serve --open` (http://127.0.0.1:8790/, macro home, `/t/NVDA` for a ticker, `/status` for sources)
- One ticker's merged news as JSON: `python -m sna news NVDA --days 7 --json`
  (rows: published_utc, source_label, publisher, title, url, summary, kind, sentiment{label, reasoning, by}, also[],
  focus = the headline names the stock, first_seen_utc)
- Live check of every source: `python -m sna doctor --symbol NVDA`
- Offline sample page (no network, made-up ticker DEMO): `python -m sna serve --offline`

## Keys

Environment variables only, never in files or chat: `MASSIVE_API_KEY` (or `POLYGON_API_KEY`), `FMP_API_KEY`,
`SEC_USER_AGENT` (name and contact email, required by SEC), optional `FINNHUB_API_KEY`, `APCA_API_KEY_ID` +
`APCA_API_SECRET_KEY`, `FRED_API_KEY`. A missing key skips that source; it is not an error.

## Facts worth knowing

- FMP news times are US Eastern, FMP economic-calendar times are UTC (measured 2026-11-07; `doctor` re-measures).
- Form 4 is due within 2 business days; 13F 45 days after quarter end, so 13F shows structure, not timing.
- CFTC TFF positions are as of Tuesday, published Friday 3:30 pm ET, index and rate futures only.
