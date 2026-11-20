(function app() {
  "use strict";
  const el = (id) => document.getElementById(id);
  const state = {
    indices: [],
    stocks: [],
    group: "index",
    previous: { index: null, stock: null },
    catalogReady: false,
    index: null,
    horizon: 5,
    range: 60,
    quotes: {},
    current: null,
    seq: 0,
    loading: false,
    auto: true,
    view: "overview",
    agentTimer: null,
    quoteTime: 0,
  };
  let requestController, quoteRequest;
  let searchTimer, searchRequest, savingWatchlist = false;
  const isStock = () => state.group === "stock";
  const unit = () => isStock() ? "元" : "点";
  const instruments = () => isStock() ? state.stocks : state.indices;
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const number = (value, digits = 2) =>
    finite(value)
      ? value.toLocaleString("zh-CN", {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        })
      : "—";
  const signed = (v, d = 2) =>
    finite(v) ? `${v > 0 ? "+" : ""}${number(v, d)}` : "—";
  const rate = (v) => (finite(v) ? `${number(v * 100, 1)}%` : "—");
  const signedRate = (v) => (finite(v) ? `${signed(v * 100)}%` : "—");
  const color = (v) =>
    finite(v) ? (v > 0 ? "up" : v < 0 ? "down" : "muted") : "muted";
  const limited = (v) => (finite(v) ? Math.max(-100, Math.min(100, v)) : 0);
  const time = (value) => {
    if (!value) return "—";
    if (/^\d{4}-\d\d-\d\d$/.test(value)) return value;
    const date = new Date(value);
    return Number.isFinite(+date)
      ? new Intl.DateTimeFormat("sv-SE", {
          timeZone: "Asia/Shanghai",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        }).format(date)
      : String(value);
  };
  function sourceLink(url, title) {
    let ok = false;
    try {
      ok = ["https:", "http:"].includes(new URL(url).protocol);
    } catch {}
    return ok
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`
      : esc(title);
  }
  const iconPaths = {
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
    refresh: '<path d="M20 8a8 8 0 1 0 .4 7M20 3v5h-5"/>',
    wave: '<path d="M2 12h5l3-7 4 14 3-7h5"/>',
    risk: '<path d="m12 3 8 3v5c0 5-4 8-8 10-4-2-8-5-8-10V6z"/><path d="m8.5 11.5 2.5 2.5 4.5-5"/>',
    layers: '<path d="m3 7 9-4 9 4-9 4zM3 12l9 4 9-4M3 17l9 4 9-4"/>',
    spark:
      '<path d="m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7Z"/>',
    news: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h3v3H7zM13 9h4m-4 3h4M7 16h10"/>',
    check: '<path d="M4 4v16h17M7 15l4-5 4 2 5-6"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    remove: '<path d="m7 7 10 10M17 7 7 17"/>',
  };
  const icon = (k) =>
    `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[k] || ""}</svg>`;
  const heading = (kind, label) =>
    `<h2 class="panel-title">${icon(kind)}${esc(label)}</h2>`;
  const link = (view, title) =>
    `<a class="panel-link" href="#${view}">${esc(title)}${icon("chevron")}</a>`;
  const statusLabels = {
    live: "盘中行情",
    latest: "最近报价",
    delayed: "来源延迟",
    cached: "缓存行情",
    snapshot: "历史快照",
    unavailable: "暂无报价",
    suspended: "暂无当日成交",
  };
  const agentLabels = {
    running: "分析中",
    queued: "排队中",
    ready: "研判完成",
    disabled: "量化模式",
    unavailable: "模型不可用",
    insufficient: "依据不足",
  };
  const bookLabels = {
    news: "市场新闻",
    policy: "政策",
    industry: "行业",
    fundamental: "基本面",
    sentiment: "情绪",
    breadth: "市场广度",
    macro: "宏观",
    filing: "公司公告",
    announcement: "公司公告",
  };
  const barsOf = (market) => (Array.isArray(market?.bars) ? market.bars : []);
  function horizons() {
    return `<div class="seg" role="group" aria-label="预测周期">${[1, 5, 20].map((n) => `<button data-horizon="${n}" aria-pressed="${n === state.horizon}">${n} 日</button>`).join("")}</div>`;
  }
  function displayIndices() {
    document.querySelectorAll("[data-group]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.group === state.group));
    });
    el("stock-count").textContent = state.stocks.length;
    el("indices").classList.toggle("stock-cards", isStock());
    el("indices").innerHTML = instruments()
      .map((idx) => {
        const quote =
          state.quotes[idx.id] ||
          (idx.id === state.current?.index?.id
            ? state.current?.market?.quote
            : null);
        const market = idx.id?.slice(0, 2).toUpperCase();
        const card = `<button class="index-tab" data-index="${esc(idx.id)}" aria-pressed="${state.index === idx.id}" ${quote ? `title="${esc(statusLabels[quote.status] || "报价")} · ${esc(time(quote.asof))}"` : ""}>
        <span class="index-name">${esc(idx.name)}${state.index === idx.id ? '<i class="index-select"></i>' : ""}</span>
        <span class="index-code">${esc(market)} · ${esc(idx.code)}${quote && ["cached", "snapshot", "delayed"].includes(quote.status) ? ` <span class="quote-lag">${esc(statusLabels[quote.status])}</span>` : ""}</span>
        ${finite(quote?.price) ? `<span class="index-tape"><span>${number(quote.price)}</span><small class="${color(quote.change_pct)}">${finite(quote.change_pct) ? `${signed(quote.change_pct)}%` : "—"}</small></span>` : ""}
      </button>`;
        if (!isStock()) return card;
        return `<div class="stock-card">${card}<button class="remove-stock" data-remove="${esc(idx.id)}" ${savingWatchlist ? "disabled" : ""} title="移出自选" aria-label="将${esc(idx.name)}移出自选">${icon("remove")}</button></div>`;
      })
      .join("");
  }
  function selectSymbol(group, id) {
    state.group = group;
    state.index = id || null;
    if (id) state.previous[group] = id;
    if (state.range === "intraday" && group === "index") state.range = 60;
    const url = new URL(location.href);
    if (id) url.searchParams.set("symbol", id);
    else url.searchParams.delete("symbol");
    history.replaceState(null, "", url);
    displayIndices();
    if (id) {
      research(true);
      return;
    }
    state.seq++;
    requestController?.abort();
    clearTimeout(state.agentTimer);
    state.current = null;
    state.loading = false;
    el("refresh").disabled = false;
    el("workspace").setAttribute("aria-busy", "false");
    status("");
    window.mountIndexChart(null, [], 0, {});
    el("workspace").innerHTML = `<section class="panel no-stocks"><h2>${state.stocks.length ? "选择要查看的股票" : "自选股列表为空"}</h2><p>通过名称或代码搜索公司，即可加入并查看股价走势。</p><button data-search-focus>搜索股票</button></section>`;
  }
  function hideSearch() {
    clearTimeout(searchTimer);
    searchRequest?.abort();
    el("search-results").hidden = true;
  }
  function renderMatches(rows) {
    if (!rows.length) {
      el("search-results").innerHTML = '<p class="search-notice" role="status">未找到匹配的 A 股上市公司。可尝试证券简称或六位代码。</p>';
      return;
    }
    el("search-results").innerHTML = rows.map((s) => {
      const saved = state.stocks.some((stock) => stock.id === s.id);
      if (s.listed === false || !s.id) {
        return `<div class="stock-match"><div><strong>${esc(s.name)}</strong><small>${esc(s.status_text || "暂无 A 股上市行情")}</small></div>${s.url ? sourceLink(s.url, "查看来源") : ""}</div>`;
      }
      return `<button type="button" class="stock-match" data-add="${esc(s.id)}" ${savingWatchlist ? "disabled" : ""}><span><strong>${esc(s.name)}</strong><small>${esc(s.exchange || s.id.slice(0, 2).toUpperCase())} · ${esc(s.code)}</small></span><span class="match-action">${saved ? "查看走势" : "＋ 加入自选"}</span></button>`;
    }).join("");
  }
  async function findStocks() {
    const query = el("stock-query").value.trim();
    hideSearch();
    if (!query) return;
    const results = el("search-results");
    results.hidden = false;
    results.innerHTML = '<p class="search-notice" role="status">正在检索上市公司…</p>';
    searchTimer = setTimeout(async () => {
      const controller = new AbortController();
      searchRequest = controller;
      const timeout = setTimeout(() => controller.abort("timeout"), 20000);
      try {
        const data = await json(`/api/search?${new URLSearchParams({ q: query })}`, {signal: controller.signal});
        if (!controller.signal.aborted) renderMatches(data.results || []);
      } catch (error) {
        if (!controller.signal.aborted || controller.signal.reason === "timeout") {
          results.innerHTML = `<p class="search-notice" role="status">检索失败，${esc(error.message)}。请重新搜索。</p>`;
        }
      } finally {
        clearTimeout(timeout);
      }
    }, 180);
  }
  async function watch(id, action) {
    if (savingWatchlist) return;
    const input = el("stock-query");
    const saved = state.stocks.find((s) => s.id === id);
    const viewStock = () => {
      input.value = "";
      hideSearch();
      state.view = "overview";
      const url = new URL(location.href);
      url.hash = "overview";
      history.replaceState(null, "", url);
      selectSymbol("stock", id);
    };
    if (action === "add" && saved) {
      viewStock();
      return;
    }
    savingWatchlist = true;
    hideSearch();
    displayIndices();
    el("watch-message").textContent = action === "add" ? "正在加入自选…" : "正在更新自选…";
    try {
      const response = await json("/api/watchlist", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ id, action }),
        signal: AbortSignal.timeout(20000),
      });
      if (!Array.isArray(response.stocks)) throw Error("自选列表数据不完整");
      state.stocks = response.stocks;
      const name = saved?.name || state.stocks.find((row) => row.id === id)?.name || id;
      if (action === "add") {
        viewStock();
        quoteTape(true);
      } else if (state.index === id) {
        selectSymbol("stock", state.stocks[0]?.id);
      }
      el("watch-message").textContent = `${name}${action === "add" ? "已加入自选" : "已移出自选"}`;
    } catch (error) {
      el("watch-message").textContent = `自选更新失败（${error.message}）`;
    } finally {
      savingWatchlist = false;
      displayIndices();
    }
  }
  function status(message) {
    el("status").innerHTML = message
      ? `<div class="banner">${esc(message)}</div>`
      : "";
  }
  function chartPanel(m, a, idx) {
    const q = m.quote || {},
      bars = barsOf(m);
    const fallback = !finite(q.price) && bars.length ? bars.at(-1) : null;
    const price = fallback ? fallback.close : q.price;
    const forMetrics = fallback || q;
    const stat = (label, key) =>
      `<div><span>${label}</span><strong>${number(forMetrics[key])}</strong></div>`;
    const statusKey = m.meta?.quote_status || "unavailable";
    const label = m.meta?.suspended ? statusLabels.suspended : fallback ? "历史收盘" : statusLabels[statusKey] || "最近报价";
    const intraday = isStock() && state.range === "intraday";
    const intradayInfo = m.intraday || {};
    const ranges = [[20, "1月"], [60, "3月"], [120, "6月"], [250, "1年"], [100000, "全部"]];
    if (isStock()) ranges.unshift(["intraday", "分时"]);
    return `<section class="panel chart-panel" aria-label="${isStock() ? "股票" : "指数"}行情与走势">
      <div class="quote-head"><div><div class="instrument"><h2>${esc(idx.name)}</h2><span class="ticker">${esc(idx.code)}</span></div>
        <div class="quote-line"><strong class="quote-price">${number(price)}<small class="price-unit">${unit()}</small></strong>
        ${!fallback && finite(q.change) ? `<span class="delta ${color(q.change)}">${signed(q.change)}${finite(q.change_pct) ? ` (${signed(q.change_pct)}%)` : ""}</span>` : ""}</div>
        <p class="asof">${fallback ? "收盘日期" : "行情时间"} ${esc(time(fallback?.date || q.asof))}${q.source && !fallback ? ` · ${esc(q.source)}` : ""}</p></div>
        <span class="tag ${statusKey === "live" && !fallback ? "live" : ""}">${esc(label)}</span></div>
      <div class="chart-tools"><div class="legend"><span><i></i>${intraday ? "分时股价" : "收盘走势"}</span>${!intraday && a.status === "ok" ? `<span><i class="band"></i>${a.interval_basis === "volatility" ? "波动参考" : "期末区间"}</span>` : ""}</div>
      <div class="seg" role="group" aria-label="走势图周期">${ranges
        .map(
          ([n, t]) =>
            `<button aria-pressed="${n === state.range}" data-range="${n}">${t}</button>`,
        )
        .join("")}</div></div>
      ${isStock() ? `<p class="chart-dateline">${intraday
        ? esc([intradayInfo.date, intradayInfo.source, statusLabels[intradayInfo.status]].filter(Boolean).join(" · ") || "暂无分时数据")
        : esc([m.meta?.history_basis || "", bars.length ? `共 ${bars.length} 个收盘交易日` : "暂无收盘日线"].filter(Boolean).join(" · "))}</p>` : ""}
      <div id="chart" class="chart-wrap"></div>
      <div class="ohlc">${stat("开盘", "open")}${stat("最高", "high")}${stat("最低", "low")}<div><span>${fallback ? "收盘" : "昨收"}</span><strong>${number(fallback ? fallback.close : q.prev_close)}</strong></div></div></section>`;
  }
  function forecast(a, agent) {
    const direction = a.direction || "数据不足";
    const cls =
      direction === "偏强" ? "up" : direction === "偏弱" ? "down" : "";
    const range = a.interval || {};
    return `<section class="panel forecast panel-pad">
      <div class="panel-top">${heading("wave", "趋势研判")}<span class="mini-tag">${a.historical ? "历史复盘" : "收盘模型"}</span></div>
      <div class="horizon-pick"><span class="horizon-label">预测交易日</span>${horizons()}</div>
      <div class="signal"><span class="caption">未来 ${state.horizon} 个交易日</span><div class="signal-core">
      <h3 class="${cls}">${esc(direction)}</h3><div class="signal-score"><b>${signed(a.score, 0)}</b>综合因子分</div></div></div>
      <div class="score-meter" aria-label="${esc(direction)}">${finite(a.score) ? `<i style="left:${(limited(a.score) + 100) / 2}%"></i>` : ""}</div>
      <div class="meter-label"><span>偏弱</span><span>中性</span><span>偏强</span></div>
      <div class="forecast-range"><div class="row"><span class="overline">${a.interval_basis === "volatility" ? `波动参考区间（${unit()}）` : isStock() ? "期末情景股价（元）" : "期末情景点位"}</span><span class="overline">基于 ${esc(a.as_of || "—")} 收盘</span></div>
      <div class="range-strip">${[
        ["下沿", "low"],
        ["中枢", "base"],
        ["上沿", "high"],
      ]
        .map(
          ([label, key]) =>
            `<div><span>${label}</span><strong>${number(range[key])}</strong><em>${signedRate(range["return_" + key])}</em></div>`,
        )
        .join("")}</div></div>
      <div class="actionbox"><span class="overline">${icon("spark")} 条件策略<span id="agent-status">${esc(reviewStatus(agent))}</span></span><div id="decision">${esc(agent.decision || a.strategy?.action || "等待有效数据后生成策略。")}</div></div></section>`;
  }
  function barTrack(score) {
    const s = limited(score);
    return `<div class="factor-track" aria-hidden="true"><i class="${s >= 0 ? "pos" : "neg"}" style="left:${s < 0 ? 50 + s / 2 : 50}%;width:${Math.abs(s) / 2}%"></i></div>`;
  }
  function factorPanel(a, full) {
    const factors = Array.isArray(a.factors) ? a.factors : [];
    const rows = full
      ? factors
      : factors
          .slice()
          .sort(
            (x, y) =>
              (y.weight || 0) * Math.abs(y.score || 0) -
              (x.weight || 0) * Math.abs(x.score || 0),
          )
          .slice(0, 5);
    const content = full
      ? `<div class="full-factors">${rows
          .map(
            (
              f,
            ) => `<article class="full-factor"><div class="factor-heading"><h3>${esc(f.name)}</h3><b class="num ${color(f.score)}">${signed(f.score, 0)}</b></div>
      <div class="factor-meta">${esc(f.group)} · 模型权重 ${rate(f.weight)}</div>${barTrack(f.score)}<p>${esc(f.detail)}</p></article>`,
          )
          .join("")}</div>`
      : `<div class="factor-summary"><div class="factor-row head"><span>因子</span><span>方向强度</span><span>得分</span><span>权重</span></div>
      ${rows.map((f) => `<div class="factor-row"><span>${esc(f.name)}</span>${barTrack(f.score)}<span class="num ${color(f.score)}">${signed(f.score, 0)}</span><span class="weight">${rate(f.weight)}</span></div>`).join("")}</div>`;
    return `<section class="panel panel-pad${full ? " wide-panel" : ""}"><div class="panel-top">${heading("layers", full ? "模型因子" : "因子贡献")}${full ? `<span class="sub">${factors.length} 项</span>` : link("factors", "全部因子")}</div>${factors.length ? content : '<p class="empty">本次计算缺少有效因子</p>'}</section>`;
  }
  function riskPanel(a) {
    const s = a.strategy || {};
    const row = (label, v, cls = "") =>
      `<div class="strategy-line"><dt>${label}</dt><dd class="${cls}">${esc(v || "—")}</dd></div>`;
    return `<section class="panel panel-pad"><div class="panel-top">${heading("risk", "策略与风控")}</div><dl class="strategy-lines">
      ${row("风险阈值", finite(s.stop) ? `${number(s.stop)} ${unit()}` : "—", "stop")}${row("止损条件", s.stop_note)}${row("触发条件", s.trigger)}${row("仓位参考", s.position)}${row("复核", s.review)}</dl></section>`;
  }
  function reviewStatus(agent) {
    if (agent.provider === "off" || agent.status === "disabled") return "仅量化";
    const name = agent.model || "AI 复核";
    return name + " · " + (agentLabels[agent.status] || "待更新");
  }
  function agentBody(agent) {
    const has = agent.summary || agent.risk || agent.refs?.length;
    const refName = (ref) => {
      if (ref === "M") return "M 量化模型";
      if (ref === "Q") return "Q 行情";
      const match = /^E(\d+)$/.exec(ref);
      const evidence =
        match && state.current?.market?.evidence?.[Number(match[1]) - 1];
      return evidence ? `${ref} ${evidence.title}` : ref;
    };
    return `<div class="insight-head">${heading("spark", "AI 复核")}<span class="info">${esc(agentLabels[agent.status] || "待更新")}</span></div>
      ${agent.summary ? `<p>${esc(agent.summary)}</p>` : ""}${agent.risk ? `<p><strong>风险观察</strong>　${esc(agent.risk)}</p>` : ""}
      ${!has || agent.message ? `<p>${esc(agent.message || "等待当前研究结果。")}</p>` : ""}
      ${agent.refs?.length ? `<div class="data-line">依据 ${agent.refs.map((ref) => esc(refName(ref))).join(" · ")}</div>` : ""}
      ${agent.model || agent.updated_at ? `<div class="data-line">${agent.model ? `<span>模型 ${esc(agent.model)}</span>` : ""}${agent.updated_at ? `<span>更新 ${esc(time(agent.updated_at))}</span>` : ""}</div>` : ""}`;
  }
  function notes(details, key = "notes", title = "数据与方法说明") {
    const values = [...new Set((details || []).filter(Boolean))];
    return values.length
      ? `<details class="notes" data-detail="${esc(key)}"><summary>${esc(title)}（${values.length}）</summary><ul>${values.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`
      : "";
  }
  function holdings(e) {
    if (!e.holdings?.length) return "";
    const rows = e.holdings
      .map(
        (s) =>
          `<tr><td>${esc(s.name)}<small>${esc(s.code)}</small></td><td>${esc(s.sector || "—")}</td><td>${number(s.weight_pct)}%</td><td>${finite(s.revenue_yoy) ? `${number(s.revenue_yoy)}%` : "—"}</td><td>${finite(s.profit_yoy) ? `${number(s.profit_yoy)}%` : "—"}</td><td>${esc(s.period || "—")}</td><td>${esc(s.disclosed_at || "—")}</td></tr>`,
      )
      .join("");
    return `<details class="notes" data-detail="hold-${esc(e.title)}"><summary>查看 ${e.holdings.length} 家成份股财报与权重</summary>
      <div class="data-line"><span>权重日期 ${esc(e.weights_date || "—")}</span>${e.weight_url ? sourceLink(e.weight_url, "权重来源") : ""}</div>
      <div class="table-scroll"><table><thead><tr>${["成份股", "行业", "指数权重", "营收同比", "净利同比", "报告期", "披露日"].map((k) => `<th>${k}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
      ${e.sectors?.length ? `<p>已覆盖行业　${e.sectors.map((s) => `${esc(s.name)} ${number(s.weight_pct)}%`).join(" · ")}</p>` : ""}</details>`;
  }
  function companyReport(e) {
    const r = e.report;
    if (!r || !isStock()) return "";
    const amount = (v) => finite(v) ? `${number(v / 100000000)} 亿元` : "—";
    const growth = (v) => finite(v) ? `${signed(v)}%` : "—";
    return `<details class="notes" data-detail="report-${esc(e.title)}"><summary>查看公司财报</summary>
      <div class="data-line"><span>${esc(r.name)} · ${esc(r.code)} · ${esc(r.sector || "所属行业待补充")}</span><span>报告期 ${esc(r.period || "—")}</span><span>披露日 ${esc(r.disclosed_at || "—")}</span>${e.publication_url ? sourceLink(e.publication_url, "财报原文") : ""}</div>
      <div class="table-scroll"><table><thead><tr><th>指标</th><th>当期金额</th><th>同比</th></tr></thead><tbody>
      <tr><td>营业收入</td><td>${amount(r.revenue)}</td><td>${growth(r.revenue_yoy)}</td></tr>
      <tr><td>归母净利润</td><td>${amount(r.net_profit)}</td><td>${growth(r.profit_yoy)}</td></tr></tbody></table></div></details>`;
  }
  function evidencePanel(m) {
    const items = m.evidence || [];
    return `<section class="panel panel-pad wide-panel"><div class="panel-top">${heading("news", "当期情报与基本面")}<span class="sub">${items.length} 条证据</span></div>
      ${
        items.length
          ? `<div class="evidence-list">${items
              .map(
                (
                  e,
                  i,
                ) => `<article><div class="evidence-meta"><span class="mini-tag">E${i + 1} · ${esc(bookLabels[e.category || e.kind] || e.category || e.kind || "情报")}</span><span>${esc(e.source || "—")}</span><span>${esc(time(e.published_at))}</span>${e.scope ? `<span>${esc(e.scope === "market" ? "全市场" : e.scope === state.index ? state.current.index.name : e.scope)}</span>` : ""}</div>
      <h3>${sourceLink(e.url, e.title || "来源资料")}</h3>${e.summary ? `<p>${esc(e.summary)}</p>` : ""}${e.basis ? `<p>计分依据　${esc(e.basis)}</p>` : ""}${companyReport(e)}${holdings(e)}</article>`,
              )
              .join("")}</div>`
          : '<p class="empty">当前数据源暂无可用于该标的的情报</p>'
      }</section>`;
  }
  function validation(a) {
    const v = a.validation || {};
    const stat = (label, val, hint) =>
      `<div class="stat"><span>${label}</span><strong>${esc(val)}</strong><small>${esc(hint)}</small></div>`;
    return `<section class="panel panel-pad wide-panel"><div class="panel-top">${heading("check", "滚动样本外验证")}<span class="sub">${state.horizon} 个交易日</span></div>
      <div class="validation-stats">${stat("历史样本", finite(v.n) ? number(v.n, 0) : "—", "已实现的预测结果")}${stat("模型方向命中率", rate(v.hit_rate), "预测与实际涨跌方向一致")}${stat("方向基准命中率", rate(v.baseline_hit_rate), "同一样本的基准结果")}
      ${stat("预测平均绝对误差", rate(v.mae), "收益率的绝对偏差")}${stat("基准平均绝对误差", rate(v.baseline_mae), "同一样本的预测基准")}${stat("区间覆盖率", rate(v.coverage), "期末实现在预测区间内")}</div>
      <p class="note">${esc(v.note || "当前样本不足以验证模型表现。")}</p>${notes(a.notes, "validation-notes", "预测方法与验证边界")}</section>`;
  }
  function forwardPanel(f) {
    const stat = (label, value) =>
      `<div class="stat"><span>${label}</span><strong>${esc(value)}</strong></div>`;
    const posture = {
      follow: "沿用量化策略",
      wait: "继续观察",
      defensive: "防守",
    };
    const recent = Array.isArray(f?.recent) ? f.recent : [];
    return `<section class="panel panel-pad wide-panel">${heading("clock", "前向跟踪")}
      ${
        f
          ? `<div class="validation-stats forward-stats">${stat("待核验", number(f.pending, 0))}${stat("已核验", number(f.settled, 0))}${stat("方向命中率", rate(f.hit_rate))}${stat("区间覆盖率", rate(f.coverage))}</div>
      ${recent.length ? `<div class="table-scroll"><table><thead><tr>${["起算日", "签发时间", "周期", "预测方向", "复核策略", "状态", "实际涨跌"].map((k) => `<th>${k}</th>`).join("")}</tr></thead><tbody>${recent.map((r) => `<tr><td>${esc(r.origin)}</td><td>${esc(time(r.issued_at))}</td><td>${esc(r.horizon)} 日</td><td>${esc(r.direction || "—")}</td><td>${esc(posture[r.posture] || "—")}</td><td>${r.status === "settled" ? "已核验" : "待核验"}</td><td class="${color(r.actual_return)}">${signedRate(r.actual_return)}</td></tr>`).join("")}</tbody></table></div>` : '<p class="note">当前标的和周期暂无已登记的预测。</p>'}
      <p class="note">记录在下一交易日开盘前首次完成的模型复核结果，按第 ${state.horizon} 个交易日的实际收盘核验。方向命中按期末情景中枢相对于起算收盘的涨跌方向计算。</p>`
          : '<p class="note">本次响应未包含前向跟踪记录。</p>'
      }</section>`;
  }
  function context(idx) {
    return `<div class="panel panel-pad context"><strong>${esc(idx.name)}</strong><span class="ticker">${esc(idx.code)}</span><span>预测交易日</span>${horizons()}</div>`;
  }
  function render() {
    const view = state.view;
    document.querySelectorAll("nav a").forEach((a) => {
      if (a.dataset.view === view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    el("page-title").textContent = {
      overview: "A 股研究台",
      factors: "因子与情报",
      validation: "历史验证",
    }[view];
    if (!state.current) return;
    const {
      market: m,
      analysis: a,
      index: idx,
      review = state.current.astra || {},
      generated_at,
    } = state.current;
    const opened = [...el("workspace").querySelectorAll("details[open]")].map(
      (s) => s.dataset.detail,
    );
    const warnings = m.meta?.warnings || [];
    let html = "";
    if (view === "overview") {
      html = `<div class="work-grid">${chartPanel(m, a, idx)}${forecast(a, review)}</div>
        <div class="detail-grid">${factorPanel(a, false)}${riskPanel(a)}</div>
        <section class="panel panel-pad insight" id="agent-card">${agentBody(review)}</section>`;
    } else if (view === "factors") {
      html = context(idx) + factorPanel(a, true) + evidencePanel(m);
    } else
      html = context(idx) + validation(a) + forwardPanel(state.current.forward);
    const q = m.quote || {};
    const src = m.meta?.history_source;
    html += `<div class="data-line"><span>研究生成 ${esc(time(generated_at))}</span>${q.source ? `<span>报价 ${sourceLink(q.url, q.source)}</span>` : ""}${src ? `<span>日线 ${sourceLink(m.meta?.history_url, src)}</span>` : ""}</div>${notes([...warnings, ...(view === "validation" ? [] : a.notes || [])], "sources")}`;
    el("workspace").innerHTML = html;
    el("workspace")
      .querySelectorAll("details")
      .forEach((d) => {
        d.open = opened.includes(d.dataset.detail);
      });
    window.mountIndexChart(el("chart"), barsOf(m), state.range, a, m.intraday);
  }
  function pending() {
    state.current = null;
    el("workspace").innerHTML =
      '<div class="initial"><span class="loader"></span>正在读取行情并计算预测…</div>';
  }
  function errorState() {
    el("workspace").innerHTML =
      '<div class="panel fatal"><h2>暂时无法读取研究数据</h2><p class="sub">请检查本地服务是否运行，再重新获取行情。</p><button class="refresh" data-retry>重新加载</button></div>';
  }
  async function json(path, options = {}) {
    const response = await fetch(path, { cache: "no-store", ...options });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw Error(detail.error || `HTTP ${response.status}`);
    }
    return response.json();
  }
  function updateCurrentQuote() {
    if (!state.current || !Object.hasOwn(state.quotes, state.index)) return;
    const m = state.current.market;
    const next = state.quotes[state.index];
    if (!next || !m.quote || next.asof >= m.quote.asof) {
      m.quote = next;
      m.meta.quote_status = next?.status || "unavailable";
    } else state.quotes[state.index] = m.quote;
    if (state.view === "overview" && el("chart")) {
      const fragment = document.createElement("template");
      fragment.innerHTML = chartPanel(
        m,
        state.current.analysis,
        state.current.index,
      );
      const panel = el("chart").parentElement;
      for (const selector of [".quote-head", ".ohlc"]) {
        panel
          .querySelector(selector)
          .replaceWith(fragment.content.querySelector(selector));
      }
    }
  }
  function quoteTape(force = false) {
    if (quoteRequest || (!force && Date.now() - state.quoteTime < 12000))
      return;
    quoteRequest = json("/api/quotes", { signal: AbortSignal.timeout(45000) })
      .then((data) => {
        state.quotes = data.quotes || {};
        state.quoteTime = Date.now();
        updateCurrentQuote();
        displayIndices();
      })
      .catch(() => {})
      .finally(() => {
        quoteRequest = null;
      });
  }
  function scheduleAgent(seq) {
    clearTimeout(state.agentTimer);
    if (
      !state.auto ||
      !state.current ||
      !["queued", "running"].includes((state.current.review || state.current.astra)?.status)
    )
      return;
    state.agentTimer = setTimeout(async () => {
      if (seq !== state.seq || !state.current) return;
      if (!document.hidden) {
        try {
          const data = await json(
            `/api/review?${new URLSearchParams({ index: state.index, horizon: state.horizon })}`,
            { signal: AbortSignal.timeout(15000) },
          );
          if (seq !== state.seq || !state.current) return;
          const review = data.review || data.astra;
          if (review) {
            state.current.review = review;
            if (el("agent-card"))
              el("agent-card").innerHTML = agentBody(review);
            if (el("agent-status"))
              el("agent-status").textContent =
                reviewStatus(review);
            if (el("decision"))
              el("decision").textContent =
                review.decision ||
                state.current.analysis?.strategy?.action ||
                "等待有效数据后生成策略。";
          }
        } catch {}
      }
      if (seq === state.seq) scheduleAgent(seq);
    }, 7000);
  }
  async function research(changed = false) {
    if (!state.index) return;
    const seq = ++state.seq;
    requestController?.abort();
    requestController = new AbortController();
    const timeout = setTimeout(() => {
      if (seq === state.seq) requestController.abort();
    }, 90000);
    clearTimeout(state.agentTimer);
    state.loading = true;
    el("refresh").disabled = true;
    el("workspace").setAttribute("aria-busy", "true");
    status("");
    if (changed || !state.current) pending();
    try {
      const data = await json(
        `/api/research?${new URLSearchParams({ index: state.index, horizon: state.horizon })}`,
        { signal: requestController.signal },
      );
      if (seq !== state.seq) return;
      if (!data.market || !data.analysis || !data.index)
        throw Error("研究结果字段不完整");
      state.current = data;
      const researchQuote = data.market.quote;
      if (
        researchQuote &&
        (!state.quotes[state.index] ||
          researchQuote.asof >= state.quotes[state.index].asof)
      )
        state.quotes[state.index] = researchQuote;
      else if (state.quotes[state.index]) {
        data.market.quote = state.quotes[state.index];
        data.market.meta.quote_status = data.market.quote.status;
      }
      render();
      displayIndices();
      scheduleAgent(seq);
    } catch (error) {
      if (seq !== state.seq) return;
      if (state.current) status("刷新失败，当前展示上一次取得的研究结果。");
      else {
        errorState();
        status(
          `数据请求失败（${error.name === "AbortError" ? "请求超时" : error.message}）`,
        );
      }
    } finally {
      clearTimeout(timeout);
      if (seq === state.seq) {
        state.loading = false;
        el("refresh").disabled = false;
        el("workspace").setAttribute("aria-busy", "false");
      }
    }
  }
  function viewFromHash() {
    state.view =
      { factors: "factors", validation: "validation" }[
        location.hash.slice(1)
      ] || "overview";
    render();
  }
  async function init() {
    el("refresh").disabled = true;
    try {
      const data = await json("/api/catalog", {
        signal: AbortSignal.timeout(15000),
      });
      state.indices = data.indices;
      state.stocks = data.stocks || [];
      state.catalogReady = true;
      if (!state.indices?.length) throw Error("暂无可选指数");
      const deepLink = new URLSearchParams(location.search).get("symbol");
      const listed = state.indices.concat(state.stocks);
      const chosen = listed.find((s) => s.id === deepLink) || listed.find((s) => s.id === data.default) || state.indices[0];
      state.group = state.stocks.some((s) => s.id === chosen.id) ? "stock" : "index";
      state.index = chosen.id;
      state.previous.index = data.default && state.indices.some((i) => i.id === data.default) ? data.default : state.indices[0].id;
      state.previous[state.group] = state.index;
      el("stock-query").disabled = false;
      if (/^(sh|sz|bj)\d{6}$/.test(deepLink) && chosen.id !== deepLink) {
        selectSymbol("stock", null);
        el("watch-message").textContent = "此证券尚未加入本机自选。请核对搜索结果后加入。";
        el("stock-query").value = deepLink.slice(2);
        el("stock-query").focus();
        quoteTape();
        return;
      }
      displayIndices();
      quoteTape();
      await research(true);
    } catch (err) {
      errorState();
      status(`证券目录未就绪（${err.message}）`);
    } finally {
      el("refresh").disabled = false;
    }
  }
  function refresh() {
    if (state.catalogReady && !state.index && isStock()) {
      el("stock-query").focus();
      return;
    }
    if (!state.index) {
      init();
      return;
    }
    quoteTape(true);
    research();
  }
  document.addEventListener("click", (e) => {
    if (!el("stock-finder").contains(e.target)) hideSearch();
    const btn = e.target.closest("button");
    if (!btn) return;
    if (btn.dataset.add) {
      watch(btn.dataset.add, "add");
    } else if (btn.dataset.remove) {
      watch(btn.dataset.remove, "remove");
    } else if (btn.hasAttribute("data-search-focus")) {
      el("stock-query").focus();
    } else if (btn.dataset.group && state.catalogReady && btn.dataset.group !== state.group) {
      const group = btn.dataset.group;
      const choices = group === "stock" ? state.stocks : state.indices;
      const previous = choices.find((row) => row.id === state.previous[group]);
      selectSymbol(group, previous?.id || choices[0]?.id);
    } else if (btn.dataset.index && btn.dataset.index !== state.index) {
      selectSymbol(state.group, btn.dataset.index);
    } else if (
      btn.dataset.horizon &&
      Number(btn.dataset.horizon) !== state.horizon
    ) {
      state.horizon = Number(btn.dataset.horizon);
      research(true);
    } else if (btn.dataset.range && state.current) {
      state.range = btn.dataset.range === "intraday" ? "intraday" : Number(btn.dataset.range);
      render();
      el("workspace").querySelector(`[data-range="${state.range}"]`)?.focus({preventScroll: true});
    } else if (btn.id === "refresh" || btn.hasAttribute("data-retry"))
      refresh();
  });
  el("stock-query").addEventListener("input", (event) => {
    if (!event.isComposing) findStocks();
  });
  el("stock-query").addEventListener("compositionend", findStocks);
  el("stock-query").addEventListener("focus", () => {
    if (el("stock-query").value.trim() && el("search-results").hidden) findStocks();
  });
  el("stock-finder").addEventListener("focusout", (event) => {
    if (!el("stock-finder").contains(event.relatedTarget)) hideSearch();
  });
  el("stock-finder").addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    const input = el("stock-query");
    const box = el("search-results");
    if (event.key === "Escape") {
      input.focus();
      hideSearch();
      return;
    }
    const options = [...box.querySelectorAll("button:not(:disabled)")];
    if (box.hidden || !options.length) return;
    const i = options.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = event.key === "ArrowDown" ? (i + 1) % options.length : (i <= 0 ? options.length - 1 : i - 1);
      options[next].focus();
    } else if (event.key === "Enter" && document.activeElement === input) {
      event.preventDefault();
      // Explicit selection prevents an ambiguous query from adding the wrong company.
      options[0].focus();
    }
  });
  el("auto").addEventListener("change", (e) => {
    state.auto = e.target.checked;
    if (state.auto && !state.loading) refresh();
    else if (!state.auto) clearTimeout(state.agentTimer);
  });
  window.addEventListener("hashchange", viewFromHash);
  window.addEventListener("model-settings-changed", () => {
    if (state.index) research(true);
  });
  const clockFormat = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  const editionFormat = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric", weekday: "long",
  });
  const clockTick = () => {
    const now = new Date();
    el("clock").textContent = clockFormat.format(now);
    el("today").textContent = editionFormat.format(now);
  };
  document.querySelectorAll("[data-icon]").forEach((v) => {
    v.innerHTML = icon(v.dataset.icon);
  });
  clockTick();
  setInterval(clockTick, 1000);
  setInterval(() => {
    if (state.auto && !document.hidden) quoteTape();
  }, 15000);
  setInterval(() => {
    if (state.auto && !document.hidden && !state.loading) research();
  }, 60000);
  viewFromHash();
  init();
})();
