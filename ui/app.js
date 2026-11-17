"use strict";
// Stock news UI. One page, rendered by path: / (macro), /t/SYM (one ticker), /status (sources and keys).
// Every card asks its own endpoint, so a slow source only delays its own card. Text from outside (headlines,
// summaries, names) only ever reaches the page through textContent, and only http(s) links are made clickable.

const $app = document.getElementById("app");
const TZ = "America/New_York";
const F_TIME = new Intl.DateTimeFormat("zh-CN", {timeZone: TZ, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"});
const F_DAY = new Intl.DateTimeFormat("zh-CN", {timeZone: TZ, month: "long", day: "numeric", weekday: "short"});
const F_KEY = new Intl.DateTimeFormat("en-CA", {timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit"});
const SVG = "http://www.w3.org/2000/svg";
const KIND = {news: "新闻", press: "新闻稿", analysis: "观点"};
const SENT = {positive: ["正面", "pos"], negative: ["负面", "neg"], neutral: ["中性", ""]};
const ACTION = {upgrade: "上调", downgrade: "下调", maintain: "维持", initialise: "首次覆盖", initialize: "首次覆盖", init: "首次覆盖", reiterate: "重申"};

// ---------- small helpers ----------

function safeUrl(u) {
  if (typeof u !== "string" || !u) return null;
  if (u.startsWith("/") && !u.startsWith("//")) return u;
  try { const p = new URL(u); return p.protocol === "http:" || p.protocol === "https:" ? p.href : null; } catch { return null; }
}

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "href") { const u = safeUrl(v); if (u) el.setAttribute("href", u); }
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function ext(url, text, cls) {
  const u = safeUrl(url);
  return u ? h("a", {href: u, target: "_blank", rel: "noopener noreferrer", class: cls}, text) : h("span", {class: cls}, text);
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
    localStorage.setItem(key, JSON.stringify(value));
  } catch { return null; }
}

const fmt = {
  num(v, d = 2) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
  },
  auto(v) { return v == null || !isFinite(v) ? "—" : fmt.num(v, Math.abs(v) >= 1000 ? 0 : 2); },
  int(v) { return v == null || !isFinite(v) ? "—" : Math.round(v).toLocaleString("en-US"); },
  signed(v, d = 2, unit = "") {
    if (v == null || !isFinite(v)) return "—";
    const sign = v > 0 ? "+" : v < 0 ? "−" : "";
    return sign + Math.abs(v).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d}) + unit;
  },
  cn(v, unit = "") {   // 1.2 万 / 3.4 亿
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + " 万亿" + unit;
    if (a >= 1e8) return (v / 1e8).toFixed(a >= 1e10 ? 0 : 1) + " 亿" + unit;
    if (a >= 1e4) return (v / 1e4).toFixed(a >= 1e6 ? 0 : 1) + " 万" + unit;
    return fmt.int(v) + unit;
  },
};

function tone(v) { return v > 0 ? "up" : v < 0 ? "down" : "flat"; }

function timeET(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  const p = Object.fromEntries(F_TIME.formatToParts(d).map(x => [x.type, x.value]));
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

function dayKey(iso) { const d = new Date(iso); return isNaN(d) ? "" : F_KEY.format(d); }

function ago(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  if (!isFinite(ms)) return "";
  const m = Math.round(ms / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  if (m < 48 * 60) return `${Math.round(m / 60)} 小时前`;
  return `${Math.round(m / 1440)} 天前`;
}

function spark(values, w = 110, ht = 24) {
  const vals = (values || []).filter(v => typeof v === "number" && isFinite(v));
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "spark");
  svg.setAttribute("width", w);
  svg.setAttribute("height", ht);
  svg.setAttribute("viewBox", `0 0 ${w} ${ht}`);
  svg.setAttribute("aria-hidden", "true");
  if (vals.length < 2) return svg;
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const x = i => 2 + (i / (vals.length - 1)) * (w - 4);
  const y = v => ht - 2 - ((v - min) / span) * (ht - 4);
  if (min < 0 && max > 0) {
    const zero = document.createElementNS(SVG, "line");
    zero.setAttribute("x1", 0); zero.setAttribute("x2", w); zero.setAttribute("y1", y(0)); zero.setAttribute("y2", y(0));
    svg.append(zero);
  }
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("d", vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(""));
  const dot = document.createElementNS(SVG, "circle");
  dot.setAttribute("cx", x(vals.length - 1)); dot.setAttribute("cy", y(vals[vals.length - 1])); dot.setAttribute("r", 2);
  svg.append(path, dot);
  return svg;
}

async function api(path, refresh) {
  const url = path + (refresh ? (path.includes("?") ? "&" : "?") + "refresh=1" : "");
  const r = await fetch(url, {headers: {Accept: "application/json"}});
  let data = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  if (!r.ok || !data) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}

// ---------- cards and source status ----------

function card(title, sub) {
  const srcs = h("div", {class: "srcs"});
  const btn = h("button", {class: "ghost", type: "button", title: "跳过缓存，重新抓取"}, "刷新");
  const body = h("div", {class: "card-body"});
  const el = h("section", {class: "card"},
    h("div", {class: "card-head"}, title ? h("h2", {}, title) : null, sub ? h("span", {class: "sub"}, sub) : null, srcs, btn), body);
  return {el, body, srcs, btn};
}

function pills(sources) {
  return (sources || []).map(s => {
    let cls = "src", text = s.label, tip;
    if (s.skipped) { cls += " skip"; tip = s.skipped; }
    else if (!s.ok) { cls += " fail"; tip = s.error || "失败"; }
    else {
      if (s.stale) cls += " stale";
      text += ` ${s.count}`;
      tip = [s.error, s.fetched_at ? `抓取于 ${timeET(s.fetched_at)}（美东）` : null].filter(Boolean).join("\n") || "正常";
    }
    return h("span", {class: cls, title: tip}, text);
  });
}

function issues(sources) {
  const lines = (sources || []).filter(s => s.skipped || !s.ok || s.stale).map(s =>
    h("div", {}, h("b", {}, s.label + "："), s.skipped ? s.skipped : s.error || "失败"));
  if (!lines.length) return null;
  return h("div", {class: "small muted issues"}, h("div", {}, lines),
    h("div", {}, "缺 key 的来源会跳过，不算错误；怎么设置见 ", h("a", {href: "/status"}, "数据源"), " 页。"));
}

function load(c, path, render) {
  const run = async (refresh) => {
    c.btn.disabled = true;
    c.body.replaceChildren(h("div", {class: "empty"}, h("span", {class: "spin"}), refresh ? "重新抓取中…" : "加载中…"));
    try {
      const data = await api(typeof path === "function" ? path() : path, refresh);
      c.srcs.replaceChildren(...pills(data.sources));
      c.body.replaceChildren();
      render(data, c.body);
      const note = issues(data.sources);
      if (note) c.body.append(note);
    } catch (e) {
      c.body.replaceChildren(h("div", {class: "error"}, "没取到：" + e.message));
    } finally {
      c.btn.disabled = false;
    }
  };
  c.btn.onclick = () => run(true);
  c.reload = run;
  run(false);
  return c;
}

function table(head, rows, opts = {}) {
  const thead = h("thead", {}, h("tr", {}, head.map(col => {
    const [label, cls] = Array.isArray(col) ? col : [col, null];
    return h("th", {class: cls}, label);
  })));
  const t = h("table", {}, thead, h("tbody", {}, rows));
  return opts.scroll ? h("div", {class: "table-scroll"}, t) : t;
}

function seg(options, current, onPick) {
  const wrap = h("div", {class: "seg"});
  for (const [value, label] of options) {
    const b = h("button", {type: "button", class: value === current ? "on" : null}, label);
    b.onclick = () => { wrap.querySelectorAll("button").forEach(x => x.classList.remove("on")); b.classList.add("on"); onPick(value); };
    wrap.append(b);
  }
  return wrap;
}

// ---------- search, recent tickers, navigation ----------

function cleanSymbol(raw) {
  const s = String(raw || "").trim().toUpperCase().replace(/^\$/, "");
  return /^[A-Z][A-Z0-9.\-]{0,9}$/.test(s) ? s : null;
}

function go(sym) {
  const s = cleanSymbol(sym);
  if (s) location.href = "/t/" + encodeURIComponent(s);
  return !!s;
}

function remember(sym) {
  const list = (store("sna.recent") || []).filter(x => x !== sym);
  list.unshift(sym);
  store("sna.recent", list.slice(0, 12));
}

function recentChips() {
  const list = store("sna.recent") || [];
  return h("div", {class: "recent-chips"}, list.length ? h("span", {class: "small muted"}, "最近：") : null,
    list.map(s => h("a", {class: "chip-link", href: "/t/" + encodeURIComponent(s)}, s)));
}

function setNav(which) {
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.nav === which));
}

document.getElementById("top-search").addEventListener("submit", e => {
  e.preventDefault();
  const input = document.getElementById("top-sym");
  if (!go(input.value)) input.select();
});
document.addEventListener("keydown", e => {
  if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
    e.preventDefault();
    document.getElementById("top-sym").focus();
  }
});

// ---------- news table (macro news and ticker news) ----------

function others(tickers, symbol) {
  const rest = (tickers || []).filter(t => t !== symbol);
  return rest.slice(0, 4).join(" ") + (rest.length > 4 ? ` +${rest.length - 4}` : "");
}

function newsTable(items, sources, opts = {}) {
  const hiddenByDefault = new Set(opts.hidden || []);
  const counts = {};
  for (const it of items) counts[it.source] = (counts[it.source] || 0) + 1;
  const labels = {};
  for (const s of sources || []) labels[s.name] = s.label;
  for (const it of items) labels[it.source] = labels[it.source] || it.source_label;
  const shown = new Set(Object.keys(counts).filter(k => !hiddenByDefault.has(k)));
  const state = {kind: "all", sent: "all", q: "", limit: 120, focus: false};
  const hasFocus = opts.symbol && items.some(i => i.focus === false);
  const hasSent = items.some(i => i.sentiment);
  const hasKinds = new Set(items.map(i => i.kind)).size > 1;

  const toggles = Object.keys(counts).sort((a, b) => counts[b] - counts[a]).map(src => {
    const t = h("button", {type: "button", class: "toggle" + (shown.has(src) ? " on" : ""), title: "点一下显示或隐藏这个来源"},
      labels[src] || src, h("span", {class: "n"}, counts[src]));
    t.onclick = () => { shown.has(src) ? shown.delete(src) : shown.add(src); t.classList.toggle("on"); draw(); };
    return t;
  });
  const focusToggle = hasFocus ? h("button", {type: "button", class: "toggle", title: "只留标题里出现代码或公司名的新闻（其余是顺带提到）"},
    `只看标题提到 ${opts.symbol}`, h("span", {class: "n"}, items.filter(i => i.focus).length)) : null;
  if (focusToggle) focusToggle.onclick = () => { state.focus = !state.focus; focusToggle.classList.toggle("on"); draw(); };
  const search = h("input", {type: "search", placeholder: "在标题和摘要里搜索", "aria-label": "搜索新闻"});
  search.oninput = () => { state.q = search.value.trim().toLowerCase(); draw(); };
  const filters = h("div", {class: "filters"}, toggles,
    hasKinds ? seg([["all", "全部"], ["news", "新闻"], ["press", "新闻稿"], ["analysis", "观点"]], "all", v => { state.kind = v; draw(); }) : null,
    hasSent ? seg([["all", "全部情绪"], ["tagged", "有标签"], ["positive", "正面"], ["neutral", "中性"], ["negative", "负面"]], "all", v => { state.sent = v; draw(); }) : null,
    focusToggle, search);
  const tbody = h("tbody");
  const foot = h("div", {class: "small muted"});
  const head = ["时间（美东）", "来源", "标题"];
  if (hasSent) head.push("Massive 情绪");
  if (opts.tickers) head.push("同时提到");
  const tbl = h("div", {class: "table-scroll"}, h("table", {},
    h("thead", {}, h("tr", {}, head.map(x => h("th", {class: x.startsWith("时间") ? "nw" : null}, x)))), tbody));

  function keep(it) {
    if (!shown.has(it.source)) return false;
    if (state.focus && it.focus === false) return false;
    if (state.kind !== "all" && it.kind !== state.kind) return false;
    const label = it.sentiment && it.sentiment.label;
    if (state.sent === "tagged" && !label) return false;
    if (!["all", "tagged"].includes(state.sent) && label !== state.sent) return false;
    if (state.q && !(`${it.title} ${it.summary || ""} ${it.publisher || ""}`.toLowerCase().includes(state.q))) return false;
    return true;
  }

  function row(it) {
    const s = it.sentiment && SENT[it.sentiment.label];
    const meta = [it.publisher && it.publisher !== it.source_label ? it.publisher : null, it.author].filter(Boolean).join(" · ");
    const titleCell = h("td", {class: "title-cell"},
      it.kind && it.kind !== "news" ? h("span", {class: "tag " + it.kind}, KIND[it.kind] || it.kind) : null,
      ext(it.url, it.title, it.focus === false ? "dim" : null),
      h("div", {class: "meta"}, meta || null, it.also && it.also.length ? `${meta ? " · " : ""}另见 ${it.also.map(a => a.label).join("、")}` : null));
    const tr = h("tr", {class: "click", title: "点击展开摘要"},
      h("td", {class: "nw", title: it.published_utc ? ago(it.published_utc) : "没有发布时间"}, timeET(it.published_utc)),
      h("td", {class: "nw"}, it.source_label),
      titleCell,
      hasSent ? h("td", {class: "nw"}, s ? h("span", {class: "tag " + s[1], title: it.sentiment.reasoning || ""}, s[0]) : h("span", {class: "muted"}, "—")) : null,
      opts.tickers ? h("td", {class: "small muted"}, others(it.tickers, opts.symbol)) : null);
    tr.addEventListener("click", e => {
      if (e.target.closest("a")) return;
      const next = tr.nextElementSibling;
      if (next && next.classList.contains("detail")) { next.remove(); return; }
      const parts = [];
      if (it.summary) parts.push(h("div", {}, it.summary));
      if (it.sentiment && it.sentiment.reasoning) parts.push(h("div", {}, h("b", {}, "Massive 情绪理由："), it.sentiment.reasoning));
      if (it.also && it.also.length) parts.push(h("div", {}, h("b", {}, "其他来源："), it.also.map((a, i) => [i ? "、" : "", ext(a.url, `${a.label}${a.publisher && a.publisher !== a.label ? "（" + a.publisher + "）" : ""}`)])));
      if (it.keywords && it.keywords.length) parts.push(h("div", {class: "muted"}, "关键词：" + it.keywords.join("、")));
      if (it.first_seen_utc) parts.push(h("div", {class: "muted"}, `本机第一次抓到：${timeET(it.first_seen_utc)}（美东）`));
      if (!parts.length) parts.push(h("div", {class: "muted"}, "这条没有摘要。"));
      tr.after(h("tr", {class: "detail"}, h("td", {colspan: head.length}, parts)));
    });
    return tr;
  }

  function draw() {
    const rows = items.filter(keep);
    tbody.replaceChildren(...rows.slice(0, state.limit).map(row));
    if (!rows.length) tbody.append(h("tr", {}, h("td", {colspan: head.length, class: "empty"}, "没有符合条件的新闻。")));
    foot.replaceChildren(...[`显示 ${Math.min(rows.length, state.limit)} / ${rows.length} 条`,
      rows.length > state.limit ? h("button", {type: "button", class: "ghost", onclick: () => { state.limit += 200; draw(); }}, "显示更多") : null,
      [...hiddenByDefault].some(k => counts[k]) ? `；默认隐藏：${[...hiddenByDefault].filter(k => counts[k]).map(k => labels[k] || k).join("、")}（点上方按钮打开）` : null,
    ].filter(Boolean));
  }
  draw();
  return h("div", {}, filters, tbl, h("div", {class: "row"}, foot));
}

// ---------- macro page ----------

function renderMarket(data, body) {
  const all = [...data.market, ...data.sectors];
  if (!all.some(q => q.price != null)) {
    body.append(h("div", {class: "notice"}, "没有报价（需要 FMP_API_KEY）。下面“宏观数据”里有 FRED 的标普 500、纳指和道指收盘价，晚一个交易日。"));
    return;
  }
  const tiles = h("div", {class: "tiles"}, data.market.map(q => h("div", {class: "tile", title: q.name || q.symbol},
    h("div", {class: "lab"}, `${q.label} · ${q.symbol}`),
    h("div", {class: "px"}, fmt.num(q.price)),
    h("div", {class: "chg " + tone(q.change_pct)}, fmt.signed(q.change_pct, 2, "%")))));
  const maxAbs = Math.max(1, ...data.sectors.map(q => Math.abs(q.change_pct || 0)));
  const bars = h("div", {class: "bars"}, data.sectors.map(q => {
    const v = q.change_pct;
    const fill = h("div", {class: "fill " + (v >= 0 ? "up" : "down")});
    if (v != null) {
      const width = (Math.abs(v) / maxAbs) * 50;
      fill.style.width = width + "%";
      fill.style.left = v >= 0 ? "50%" : (50 - width) + "%";
    }
    return [h("div", {class: "name"}, `${q.label} `, h("span", {class: "muted small"}, q.symbol)),
      h("div", {class: "track"}, h("div", {class: "mid"}), fill),
      h("div", {class: "val " + tone(v)}, fmt.signed(v, 2, "%"))];
  }));
  body.append(h("div", {class: "grid2"}, h("div", {}, h("h3", {}, "主要资产（ETF）"), tiles),
    h("div", {}, h("h3", {}, "板块 ETF 今日涨跌"), bars)));
}

function changeText(v, unit) {
  if (v == null) return "—";
  if (unit === "bp") return fmt.signed(v, 0, " bp");
  if (unit === "pct") return fmt.signed(v, 1, "%");
  if (unit === "pp") return fmt.signed(v, 2, " 点");
  return fmt.signed(v, Math.abs(v) >= 100 ? 0 : 2);
}

function valueText(r) {
  if (r.value == null) return "—";
  if (r.unit === "%") return fmt.num(r.value, 2) + "%";
  if (r.unit === "$") return "$" + fmt.num(r.value, 2);
  return Math.abs(r.value) >= 10000 ? fmt.int(r.value) : fmt.num(r.value, Math.abs(r.value) < 10 && !Number.isInteger(r.value) ? 2 : 1);
}

function renderFred(data, body) {
  const rows = [];
  for (const g of data.groups) {
    rows.push(h("tr", {class: "group"}, h("td", {colspan: 8}, g.title)));
    for (const r of g.rows) {
      const date = r.date ? (r.freq === "monthly" ? r.date.slice(0, 7) : r.date.slice(5)) : "—";
      rows.push(h("tr", {},
        h("td", {}, ext(r.url, r.label), r.note ? h("div", {class: "small muted"}, r.note) : null,
          r.error ? h("div", {class: "small error"}, r.error) : null),
        h("td", {class: "r"}, h("b", {}, valueText(r))),
        h("td", {class: "r muted"}, date),
        h("td", {class: "r"}, changeText(r.change_prev, r.change_unit)),
        h("td", {class: "r"}, r.freq === "monthly" ? "" : changeText(r.change_1w, r.change_unit)),
        h("td", {class: "r"}, changeText(r.change_1m, r.change_unit)),
        h("td", {class: "r"}, changeText(r.change_1y, r.change_unit)),
        h("td", {}, spark(r.spark))));
    }
  }
  body.append(table(["指标", ["最新", "r"], ["日期", "r"], ["较上期", "r"], ["1 周", "r"], ["1 月", "r"], ["1 年", "r"], "走势"], rows),
    h("div", {class: "small muted"}, "bp = 基点（0.01 个百分点）；“点”= 百分点。月度数据的日期是统计月份；走势：日度近一年、周度近两年、月度近三年。"));
}

function renderCalendar(data, body) {
  const state = {us: true, high: false};
  const today = F_KEY.format(new Date());
  const holder = h("div");
  const draw = () => {
    const evs = data.events.filter(e => (!state.us || e.country === "US") && (!state.high || (e.impact || "").toLowerCase() === "high"));
    const rows = [];
    let last = null;
    for (const e of evs) {
      const key = dayKey(e.time_utc);
      if (key !== last) {
        rows.push(h("tr", {class: "group"}, h("td", {colspan: 6}, (e.time_utc ? F_DAY.format(new Date(e.time_utc)) : "时间未知") + (key === today ? "（今天）" : ""))));
        last = key;
      }
      const impact = (e.impact || "").toLowerCase();
      rows.push(h("tr", {},
        h("td", {class: "nw"}, timeET(e.time_utc).slice(6)),
        h("td", {class: "nw"}, e.country || ""),
        h("td", {}, e.event || "", impact === "high" ? [" ", h("span", {class: "tag analysis", title: "FMP 标注的高影响事件"}, "高")] : null),
        h("td", {class: "r"}, h("b", {}, e.actual ?? "")),
        h("td", {class: "r muted"}, e.estimate ?? ""),
        h("td", {class: "r muted"}, e.previous ?? "")));
    }
    if (!rows.length) rows.push(h("tr", {}, h("td", {colspan: 6, class: "empty"}, "这段时间没有符合条件的事件。")));
    holder.replaceChildren(h("div", {class: "table-scroll"}, table(["时间", "国家", "事件", ["实际", "r"], ["预期", "r"], ["前值", "r"]], rows)));
  };
  const t1 = h("button", {type: "button", class: "toggle on"}, "只看美国");
  t1.onclick = () => { state.us = !state.us; t1.classList.toggle("on"); draw(); };
  const t2 = h("button", {type: "button", class: "toggle"}, "只看高影响");
  t2.onclick = () => { state.high = !state.high; t2.classList.toggle("on"); draw(); };
  body.append(h("div", {class: "filters"}, t1, t2, h("span", {class: "small muted"}, `${data.from} 至 ${data.to}`)), holder,
    h("div", {class: "small muted"}, `已换算成美东时间（FMP 日历原始时间是 ${data.time_basis}` + (data.time_basis_measured ? "，doctor 已核对）。" : "，2026-11-07 核对过）。")));
  draw();
}

function renderFed(data, body) {
  for (const f of data.feeds) {
    body.append(h("h3", {}, f.label));
    if (!f.items.length) { body.append(h("div", {class: "empty"}, "没有内容。")); continue; }
    body.append(h("ul", {class: "plain fed"}, f.items.map(it => h("li", {},
      h("span", {class: "muted small num"}, (it.published_utc ? dayKey(it.published_utc) : "—") + "  "),
      ext(it.url, it.title, it.focus === false ? "dim" : null), it.summary ? h("div", {class: "small muted"}, it.summary) : null))));
  }
}

function netText(v) { return v == null ? "—" : fmt.signed(v, 0); }

function renderCot(data, body) {
  const rows = data.markets.map(m => {
    if (!m.found) return h("tr", {}, h("td", {}, m.label), h("td", {colspan: 9, class: "muted"}, `没有数据（合约代码 ${m.code}，可在 config/feeds.json 修改）`));
    const cell = g => [
      h("td", {class: "r", title: `多 ${fmt.int(g.long)} / 空 ${fmt.int(g.short)}；占持仓 ${g.net_pct_oi ?? "—"}%`}, h("b", {}, netText(g.net))),
      h("td", {class: "r " + tone(g.change_1w)}, netText(g.change_1w)),
      h("td", {class: "r", title: "过去三年里，有多少周的净头寸不高于本周（0 = 三年最空，100 = 三年最多）"}, g.pctile_3y == null ? "—" : g.pctile_3y + "%")];
    return h("tr", {}, h("td", {title: m.name}, m.label, h("div", {class: "small muted"}, m.date)),
      cell(m.asset_mgr), cell(m.lev_money), h("td", {}, spark(m.lev_money.spark, 90, 22)));
  });
  body.append(h("div", {class: "table-scroll"}, h("table", {},
      h("thead", {},
        h("tr", {}, h("th", {rowspan: 2}, "合约"), h("th", {colspan: 3, class: "r"}, "资产管理人（共同基金、养老金等）"),
          h("th", {colspan: 3, class: "r"}, "杠杆基金（对冲基金、CTA 等）"), h("th", {rowspan: 2}, "杠杆基金近一年")),
        h("tr", {}, ["净多", "周变化", "3 年分位", "净多", "周变化", "3 年分位"].map(x => h("th", {class: "r"}, x)))),
      h("tbody", {}, rows))),
    h("div", {class: "small muted"}, data.release + "。净多 = 多头合约 − 空头合约；交易商（做市商）一栏省略，鼠标停在数字上可看多空明细。"));
}

function pageHome() {
  setNav("home");
  document.title = "宏观 · 新闻与机构行为";
  const input = h("input", {placeholder: "输入股票代码，例如 NVDA，查看新闻和机构行为", "aria-label": "股票代码", spellcheck: "false", autocomplete: "off"});
  const form = h("form", {class: "search", onsubmit: e => { e.preventDefault(); if (!go(input.value)) input.select(); }},
    input, h("button", {type: "submit"}, "查看"));
  const market = card("市场概况", "FMP 报价");
  const fred = card("宏观数据", "FRED 免费数据");
  const cal = card("经济日历", "FMP，时间为美东");
  const fed = card("美联储", "官方 RSS");
  const news = card("宏观新闻", "MarketWatch、ZeroHedge、华尔街见闻、FMP");
  const cot = card("期货持仓", "CFTC 金融期货持仓报告（TFF）");
  $app.replaceChildren(form, h("div", {class: "hint"}, "按 / 键随时搜索代码"), recentChips(),
    market.el, fred.el, h("div", {class: "grid2"}, cal.el, fed.el), news.el, cot.el);
  load(market, "/api/macro/market", renderMarket);
  load(fred, "/api/macro/fred", renderFred);
  load(cal, "/api/macro/calendar", renderCalendar);
  load(fed, "/api/macro/fed", renderFed);
  load(news, "/api/macro/news", (d, b) => b.append(newsTable(d.items, d.sources)));
  load(cot, "/api/macro/cot", renderCot);
}

// ---------- ticker page ----------

function renderHeader(sym, d, body) {
  const q = d.quote || {}, p = d.profile || {}, c = d.company || {};
  body.append(h("div", {class: "head"},
    h("span", {class: "sym"}, sym), h("span", {class: "name"}, d.name || "（没有找到公司名）"),
    q.price != null ? h("span", {class: "price"}, fmt.num(q.price)) : null,
    q.change_pct != null ? h("span", {class: tone(q.change_pct)}, `${fmt.signed(q.change, 2)}（${fmt.signed(q.change_pct, 2, "%")}）`) : null));
  const facts = [
    p.sector ? ["行业", `${p.sector}${p.industry ? " / " + p.industry : ""}`] : null,
    p.market_cap ? ["市值", fmt.cn(p.market_cap, "美元")] : null,
    q.year_low != null ? ["52 周", `${fmt.num(q.year_low)} – ${fmt.num(q.year_high)}`] : null,
    q.avg50 != null ? ["50/200 日均线", `${fmt.num(q.avg50)} / ${fmt.num(q.avg200)}`] : null,
    p.exchange ? ["交易所", p.exchange] : null,
    c.cik ? ["SEC CIK", String(c.cik)] : null,
  ].filter(Boolean);
  body.append(h("div", {class: "facts"}, facts.map(([k, v]) => h("span", {}, k + " ", h("b", {}, v)))),
    h("div", {class: "links"}, (d.links || []).map(l => ext(l.url, l.label, "chip-link"))));
  if (p.description) body.append(h("details", {class: "small muted"}, h("summary", {}, "公司简介（FMP）"), p.description));
}

function renderInsiders(d, body) {
  if (!d.summary) { body.append(h("div", {class: "empty"}, "没有数据。")); return; }
  const s = d.summary, sell = s.sell, buy = s.buy, plan = s.sell_plan;
  const share = sell.value ? Math.round(100 * plan.value / sell.value) : null;
  const other = Object.entries(s.other || {}).map(([k, n]) => `${k} ${n}`).join("，");
  body.append(h("div", {class: "kpis"},
    h("div", {class: "kpi"}, h("div", {class: "lab"}, "公开市场买入（P）"), h("div", {class: "v up"}, fmt.cn(buy.value, " 美元")), h("div", {class: "s"}, `${buy.n} 笔，${buy.people} 人`)),
    h("div", {class: "kpi"}, h("div", {class: "lab"}, "公开市场卖出（S）"), h("div", {class: "v down"}, fmt.cn(sell.value, " 美元")), h("div", {class: "s"}, `${sell.n} 笔，${sell.people} 人`)),
    h("div", {class: "kpi"}, h("div", {class: "lab"}, "其中 10b5-1 计划卖出"), h("div", {class: "v"}, share == null ? "—" : share + "%"), h("div", {class: "s"}, `${plan.n} 笔，事先约定的卖出`)),
    h("div", {class: "kpi"}, h("div", {class: "lab"}, "其他（授予、行权、缴税等）"), h("div", {class: "v"}, Object.values(s.other || {}).reduce((a, b) => a + b, 0) + " 笔"), h("div", {class: "s"}, other || "—"))));
  const all = d.transactions || [];
  const hasPS = all.some(t => !t.derivative && (t.code === "P" || t.code === "S"));
  const holder = h("div");
  const draw = mode => {
    const rows = all.filter(t => mode === "all" || (!t.derivative && (mode === "nd" || t.code === "P" || t.code === "S")));
    holder.replaceChildren(rows.length ? h("div", {class: "table-scroll"}, table(
      ["交易日", "内部人", "身份", "类型", ["股数", "r"], ["价格", "r"], ["金额", "r"], ["交易后持股", "r"], "10b5-1", "申报"],
      rows.map(t => h("tr", {},
        h("td", {class: "nw"}, t.date || "—"),
        h("td", {}, t.owner),
        h("td", {class: "small"}, (t.roles || []).join("，")),
        h("td", {class: "nw"}, h("span", {class: "tag " + (t.code === "P" ? "pos" : t.code === "S" ? "neg" : ""), title: t.code_label}, t.code || "?"), " ", h("span", {class: "small muted"}, t.code_label + (t.derivative ? "（衍生品）" : ""))),
        h("td", {class: "r"}, fmt.int(t.shares)),
        h("td", {class: "r"}, t.price ? fmt.num(t.price) : "—"),
        h("td", {class: "r"}, t.value ? fmt.cn(t.value) : "—"),
        h("td", {class: "r muted"}, fmt.int(t.after)),
        h("td", {}, t.plan_10b5_1 ? "是" : ""),
        h("td", {class: "nw"}, ext(t.url, t.filed || "文件")))))) : h("div", {class: "empty"}, "这个筛选下没有交易。"));
  };
  body.append(h("div", {class: "filters"}, seg([["ps", "只看买卖 P/S"], ["nd", "全部普通股交易"], ["all", "含衍生品"]], hasPS ? "ps" : "nd", draw)), holder,
    h("div", {class: "small muted"}, `近 ${d.window_days} 天读了 ${d.filings} 份 Form 4` + (d.capped ? "（已到上限，更早的没读）" : "") + (d.failed ? `，${d.failed} 份没读成` : "") +
      "。Form 4 要在交易后 2 个工作日内申报。"));
  draw(hasPS ? "ps" : "nd");
}

function renderFilings(d, body) {
  if (!d.company) { body.append(h("div", {class: "empty"}, "没有数据。")); return; }
  const holder = h("div");
  const views = {
    holders: () => (d.holders || []).length ? table(["申报日", "表格", "申报人", "性质"], d.holders.map(x => h("tr", {},
      h("td", {class: "nw"}, ext(x.url, x.date)), h("td", {class: "nw"}, x.form),
      h("td", {}, (x.filers || []).join("；") || h("span", {class: "muted"}, "（点日期看文件）")),
      h("td", {}, x.active ? h("span", {class: "tag active", title: "13D：持股 5% 以上且可能影响公司控制或经营"}, "主动 13D") : h("span", {class: "tag"}, "被动 13G"), x.amendment ? h("span", {class: "small muted"}, " 修正") : null)))) :
      h("div", {class: "empty"}, "近两年没有 13D/13G。"),
    events: () => (d.events || []).length ? table(["申报日", "事项", "文件"], d.events.map(x => h("tr", {},
      h("td", {class: "nw"}, x.date), h("td", {}, (x.items || []).filter(i => i.code !== "9.01").map(i => h("span", {class: "tag", title: "Item " + i.code}, i.label))),
      h("td", {class: "nw"}, ext(x.url, x.form))))) : h("div", {class: "empty"}, "近 180 天没有 8-K。"),
    other: () => (d.other || []).length ? table(["申报日", "表格", "说明", "申报人"], d.other.map(x => h("tr", {},
      h("td", {class: "nw"}, x.date), h("td", {class: "nw"}, ext(x.url, x.form)), h("td", {}, x.label),
      h("td", {class: "small"}, (x.filers || []).join("；")))))
      : h("div", {class: "empty"}, "近 180 天没有这些文件。"),
  };
  const counts = {holders: (d.holders || []).length, events: (d.events || []).length, other: (d.other || []).length};
  body.append(h("div", {class: "filters"}, seg([["holders", `大股东 13D/13G（${counts.holders}）`], ["events", `重大事件 8-K（${counts.events}）`], ["other", `增发、拟售、财报（${counts.other}）`]], "holders",
    v => holder.replaceChildren(views[v]()))), holder);
  holder.replaceChildren(views.holders());
  const due = d.next_13f;
  body.append(h("div", {class: "small muted"},
    `13F 机构持仓：季末后 45 天内申报，下一批（${due.quarter_end} 季末）截止 ${due.due}，所以 13F 看持仓结构，不看时点。` +
    "按个股汇总 13F 没有可靠的免费接口，本版先不做，可点上方 WhaleWisdom 查看。",
    d.oldest_listed ? ` SEC 最近文件列表最早到 ${d.oldest_listed}。` : ""));
}

function renderAnalysts(d, body) {
  const t = d.target;
  if (t) body.append(h("div", {class: "kpis"}, [["目标价共识", t.targetConsensus], ["中位数", t.targetMedian], ["最高", t.targetHigh], ["最低", t.targetLow]]
    .map(([k, v]) => h("div", {class: "kpi"}, h("div", {class: "lab"}, k), h("div", {class: "v"}, fmt.num(v))))));
  if (!(d.grades || []).length) { body.append(h("div", {class: "empty"}, "没有评级变动。")); return; }
  body.append(h("div", {class: "table-scroll"}, table(["日期", "机构", "动作", "评级"], d.grades.map(g => {
    const act = (g.action || "").toLowerCase();
    return h("tr", {}, h("td", {class: "nw"}, g.date || "—"), h("td", {}, g.firm || "—"),
      h("td", {class: "nw"}, h("span", {class: "tag " + (act === "upgrade" ? "pos" : act === "downgrade" ? "neg" : "")}, ACTION[act] || g.action || "—")),
      h("td", {}, g.from && g.from !== g.to ? `${g.from} → ${g.to}` : g.to || "—"));
  }))));
}

function pageTicker(sym) {
  setNav(null);
  document.title = `${sym} · 新闻与机构行为`;
  remember(sym);
  document.getElementById("top-sym").value = sym;
  const head = card(null, null);
  const state = {days: store("sna.days") || 14};
  const news = card("个股新闻", "合并去重，按发布时间倒序");
  const insiders = card("内部人交易", "SEC Form 4，近 90 天");
  const filings = card("大股东与公司文件", "SEC EDGAR");
  const analysts = card("分析师评级", "FMP");
  $app.replaceChildren(head.el, news.el, h("div", {class: "section-title"}, "机构行为"),
    insiders.el, h("div", {class: "grid2"}, filings.el, analysts.el));
  const s = encodeURIComponent(sym);
  load(head, `/api/ticker/${s}/overview`, (d, b) => renderHeader(sym, d, b));
  load(news, () => `/api/ticker/${s}/news?days=${state.days}`, (d, b) => {
    const c = d.massive_sentiment || {};
    const daysSeg = seg([[3, "3 天"], [7, "7 天"], [14, "14 天"], [30, "30 天"]], state.days, v => { state.days = v; store("sna.days", v); news.reload(false); });
    b.append(h("div", {class: "counts"}, daysSeg, h("span", {}, "共 ", h("b", {}, d.items.length), ` 条（合并前 ${d.raw_count}）`),
      c.positive + c.neutral + c.negative ? h("span", {}, "Massive 情绪：", h("b", {class: "up"}, `正面 ${c.positive}`), " / ", h("b", {}, `中性 ${c.neutral}`), " / ", h("b", {class: "down"}, `负面 ${c.negative}`)) : null),
      newsTable(d.items, d.sources, {hidden: ["gdelt"], tickers: true, symbol: sym}));
  });
  load(insiders, `/api/ticker/${s}/insiders`, renderInsiders);
  load(filings, `/api/ticker/${s}/filings`, renderFilings);
  load(analysts, `/api/ticker/${s}/analysts`, renderAnalysts);
}

// ---------- status page ----------

async function pageStatus() {
  setNav("status");
  document.title = "数据源 · 新闻与机构行为";
  $app.replaceChildren(h("div", {class: "empty"}, h("span", {class: "spin"}), "加载中…"));
  let d;
  try { d = await api("/api/status"); } catch (e) { $app.replaceChildren(h("div", {class: "error"}, e.message)); return; }
  const keys = table(["环境变量", "状态", "用途"], Object.entries(d.keys).map(([k, set]) => h("tr", {},
    h("td", {}, h("code", {}, k)), h("td", {class: set ? "up" : "muted"}, set ? "已设置" : "未设置"), h("td", {}, d.key_help[k] || ""))));
  const sources = d.sources.length ? table(["来源", "结果", "条数", "耗时", "时间（美东）", "说明"], d.sources.map(s => h("tr", {},
    h("td", {}, s.label), h("td", {class: s.skipped ? "muted" : s.ok ? "up" : "down"}, s.skipped ? "跳过" : s.ok ? (s.stale ? "用了旧缓存" : "正常") : "失败"),
    h("td", {class: "r"}, s.count), h("td", {class: "r"}, s.ms + " ms"), h("td", {class: "nw"}, timeET(s.at)),
    h("td", {class: "small"}, s.skipped || s.error || "")))) : h("div", {class: "empty"}, "这次启动后还没抓过；打开首页或个股页后再来看。");
  $app.replaceChildren(
    h("section", {class: "card"}, h("div", {class: "card-head"}, h("h2", {}, "Key 和身份")), keys,
      h("h3", {}, "怎么设置（Windows）"),
      h("div", {class: "small"}, "PowerShell 里运行下面一行（把引号里的内容换成你自己的），然后重启本服务。值只存在你电脑的用户环境变量里，不要写进文件或发到对话里。"),
      h("pre", {class: "cmd"}, '[Environment]::SetEnvironmentVariable("SEC_USER_AGENT", "Your Name your-email@example.com", "User")\n[Environment]::SetEnvironmentVariable("MASSIVE_API_KEY", "<你的 key>", "User")'),
      h("div", {class: "small muted"}, "已有 FMP_API_KEY 的话不用再设。Finnhub、Alpaca、FRED 的 key 都是可选的。")),
    h("section", {class: "card"}, h("div", {class: "card-head"}, h("h2", {}, "本次启动后的抓取结果")), h("div", {class: "card-body"}, sources)),
    h("section", {class: "card"}, h("div", {class: "card-head"}, h("h2", {}, "本地数据")),
      h("div", {class: "kv"},
        h("span", {}, "缓存"), h("span", {}, d.cache.entries != null ? `${d.cache.entries} 个响应，${fmt.cn(d.cache.bytes)} 字节（${d.cache.path}）` : d.cache.error),
        h("span", {}, "新闻历史"), h("span", {}, d.history.articles != null ? `${d.history.articles} 条，${d.history.scopes} 个代码或宏观（${d.history.path}，记录每条新闻第一次被抓到的时间）` : d.history.error),
        h("span", {}, "版本"), h("span", {}, d.version + (d.offline ? "（离线示例模式）" : "")),
        h("span", {}, "实时自检"), h("span", {}, h("code", {}, "python -m sna doctor"), " 会逐个测试所有来源，并核对 FMP 的时间基准"))));
}

// ---------- start ----------

(async function start() {
  try {
    const st = await api("/api/status");
    if (st.offline) {
      const box = document.getElementById("offline");
      box.hidden = false;
      box.append(h("div", {class: "banner"}, "离线示例数据：只用来看页面长什么样。新闻、数字和公司（DEMO）都是编的，不是真实行情。"));
    }
  } catch { /* the cards show their own errors */ }
})();

(function route() {
  const path = decodeURIComponent(location.pathname);
  const m = path.match(/^\/t\/([^/]+)$/);
  if (path === "/" || path === "") pageHome();
  else if (m && cleanSymbol(m[1])) pageTicker(cleanSymbol(m[1]));
  else if (path === "/status") pageStatus();
  else $app.replaceChildren(h("div", {class: "empty"}, "没有这个页面。", h("a", {href: "/"}, "回首页")));
})();
