(() => {
  "use strict";
  const host = document.getElementById("paper-workspace");
  const el = (id) => document.getElementById(id);
  const language = () => window.LilacI18n?.lang === "en" ? "en" : "zh";
  const say = (zh, en) => language() === "en" ? en : zh;
  const translate = (text) => window.LilacI18n?.translate?.(text) ?? text;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (char) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
  const amount = (n, digits = 2) => Number.isFinite(n)
    ? n.toLocaleString(language() === "en" ? "en-US" : "zh-CN",
      {minimumFractionDigits: digits, maximumFractionDigits: digits}) : "—";
  const yuan = (n) => Number.isFinite(n) ? "¥" + amount(n) : "—";
  const sideName = (side) => side === "buy" ? say("买入", "Buy") : say("卖出", "Sell");
  const time = (s) => {
    if (!s) return "—";
    const date = new Date(s);
    return Number.isFinite(+date) ? date.toLocaleString("sv-SE", {timeZone: "Asia/Shanghai"}) + " UTC+8" : s;
  };
  const metric = (label, value, change) => {
    const css = change > 0 ? "up" : change < 0 ? "down" : "";
    return `<div><dt>${label}</dt><dd class="${css}">${esc(value)}</dd></div>`;
  };
  const note = (s) => `<p class="note">${esc(s)}</p>`;
  const post = (payload) => ({
    method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload),
  });
  async function request(route, query, options) {
    const params = new URLSearchParams({...query, lang:language()});
    const result = await fetch("/api/paper" + route + "?" + params, {
      cache: "no-store", signal: AbortSignal.timeout(35000), ...options,
    });
    const data = await result.json();
    if (!result.ok) {
      const error = new Error(translate(data.error || `HTTP ${result.status}`));
      error.status = result.status;
      throw error;
    }
    return data;
  }

  function costExample(cost) {
    if (!cost) return "";
    return `<details class="paper-costs" data-detail="trade-costs"><summary>${say("交易成本测算", "Trading cost scenario")}</summary>
      <p class="note">${say("按参考收盘价买入，再以情景价一次卖出。净盈亏已计双边滑点和税费。", "One purchase at the reference close and one sale at the scenario price. Net P&L includes both sides’ slippage, fees and taxes.")}</p>
      <dl class="paper-metrics">${metric(say("假设股数", "Assumed shares"), amount(cost.shares, 0))}
      ${metric(say("买入总支出", "Total buy cost"), yuan(cost.entry_cash))}
      ${metric(say("保本卖出报价", "Break-even sell quote"), yuan(cost.break_even))}
      ${metric(say("中枢情景净盈亏", "Base-case net P&L"), yuan(cost.base_net_pnl), cost.base_net_pnl)}
      ${metric(say("保护位情景净盈亏", "Stop-case net P&L"), yuan(cost.stop_net_pnl), cost.stop_net_pnl)}</dl></details>`;
  }

  let active = null;
  let expanded = false;
  const key = (symbol) => "lilac.paper.pending." + symbol;
  // Keep the original order identity through a timeout or a browser refresh.
  function savedOrder(symbol) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(key(symbol)));
      return saved?.symbol === symbol && saved.request_id ? saved : null;
    } catch { return null; }
  }
  function remember(ctx, order) {
    ctx.pending = order;
    try {
      if (order) sessionStorage.setItem(key(ctx.stock.id), JSON.stringify(order));
      else sessionStorage.removeItem(key(ctx.stock.id));
    } catch { /* The in-memory identity still protects retries in this tab. */ }
  }
  function invalidateReview(ctx) {
    ctx.reviewSeq++;
    clearTimeout(ctx.timer);
    ctx.review = null;
    ctx.reviewBusy = false;
  }
  function select(stock, horizon) {
    if (active && stock?.id === active.stock.id) {
      if (horizon !== active.horizon) {
        active.horizon = horizon;
        invalidateReview(active);
        drawReview(active);
      }
      return;
    }
    if (active) invalidateReview(active);
    active = null;
    host.hidden = !stock;
    host.replaceChildren();
    if (!stock) return;
    const pending = savedOrder(stock.id);
    const ctx = active = {stock, horizon, side:pending?.side || "buy", pending, book:null,
      review:null, reviewSeq:0, reviewBusy:false, reading:false, busy:false, stale:false, preview:null};
    host.innerHTML = `<details class="paper-shell panel" id="paper-shell">
      <summary><span class="paper-heading"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="3" y="5" width="18" height="15" rx="2"/><path d="M3 10h18m-6 5h3"/></svg><strong id="paper-title">${say("A 股模拟交易与持仓复核", "A-share paper trading & position review")}</strong></span>
      <span class="paper-summary-name">${esc(language() === "en" ? stock.english || stock.code : stock.name)} <span aria-hidden="true">⌄</span></span></summary>
      <div class="paper-body"><div class="paper-subhead"><h3>${say("模拟账户", "Paper account")}</h3>
      <button class="paper-button" type="button" id="paper-refresh">${say("刷新账户", "Refresh account")}</button></div>
      <div id="paper-account"></div>
      <div class="paper-columns"><div class="paper-holding"><h3>${say("当前持仓", "Selected position")} · ${esc(stock.code)}</h3><div id="paper-holding"></div></div>
      <div class="paper-ticket"><h3>${say("模拟委托", "Paper order")}</h3><p class="note" id="paper-quote"></p>
      <form id="paper-form"><div class="paper-order-inputs"><label>${say("方向", "Side")}<select id="paper-side"><option value="buy">${sideName("buy")}</option><option value="sell">${sideName("sell")}</option></select></label>
      <label>${say("股数", "Shares")}<input id="paper-qty" inputmode="numeric" type="number" min="1" step="1" required></label>
      <button class="paper-button" id="paper-preview" type="submit">${say("预览成交", "Preview order")}</button></div></form>
      <div id="paper-estimate"></div><button class="paper-submit" id="paper-confirm" type="button" hidden></button>
      <p class="paper-feedback" id="paper-feedback" aria-live="polite"></p></div></div>
      <div class="paper-review"><div class="paper-subhead"><h3>${say("持仓 AI 复核", "AI position review")}</h3>
      <button id="paper-review" type="button" class="paper-button">${say("复核当前仓位", "Review position")}</button></div>
      <p class="note">${say("点击复核会把模拟仓位、可用现金和研究数据发送给所选模型。", "Requesting a review sends paper position, available cash and research data to the selected model.")}</p><div id="paper-advice" aria-live="polite"></div></div>
      <details class="paper-ledger"><summary>${say("账户持仓与近期成交", "Account holdings & recent fills")}</summary><div id="paper-records"></div></details></div></details>`;
    el("paper-side").value = ctx.side;
    el("paper-qty").value = pending?.quantity || (stock.id.startsWith("sh688") ? 200 : 100);
    const shell = el("paper-shell");
    shell.addEventListener("toggle", () => {
      if (ctx !== active) return;
      expanded = shell.open;
      if (expanded) {
        load(ctx);
        if (reviewWaiting(ctx)) pollReview(ctx);
      } else clearTimeout(ctx.timer);
    });
    shell.open = expanded;
    controls(ctx);
    drawReview(ctx);
  }
  function message(text, error = false) {
    const feedback = el("paper-feedback");
    feedback.textContent = text;
    feedback.classList.toggle("error", error);
  }
  function controls(ctx) {
    const locked = ctx.busy || !!ctx.pending;
    el("paper-qty").disabled = el("paper-side").disabled = locked;
    el("paper-preview").disabled = !ctx.book?.quote?.price || locked || ctx.stale;
    const confirm = el("paper-confirm");
    confirm.hidden = !ctx.pending && !ctx.preview;
    confirm.disabled = ctx.busy || (!ctx.pending && (!ctx.canTrade || ctx.stale));
    confirm.textContent = ctx.pending ? say("核对并重试原委托", "Check and retry original order")
      : say("确认模拟成交", "Confirm paper fill");
    el("paper-refresh").disabled = ctx.reading || ctx.busy;
    el("paper-review").disabled = !ctx.book || ctx.reviewBusy || reviewWaiting(ctx) || ctx.stale;
  }
  function position(ctx) {
    return ctx.book?.positions?.find((row) => row.symbol === ctx.stock.id);
  }
  function drawBook(ctx) {
    const b = ctx.book;
    const p = position(ctx);
    el("paper-account").innerHTML = `<dl class="paper-metrics account-totals">
      ${metric(say("可用现金", "Available cash"), yuan(b.cash))}
      ${metric(say("账户权益", "Account equity"), yuan(b.equity))}
      ${metric(say("总盈亏", "Total P&L"), yuan(b.total_pnl), b.total_pnl)}
      ${metric(say("已实现盈亏", "Realized P&L"), yuan(b.realized_pnl), b.realized_pnl)}</dl>`;
    el("paper-holding").innerHTML = p ? `<dl class="paper-metrics">
      ${metric(say("持股数", "Shares held"), amount(p.quantity, 0))}
      ${metric(say("可卖股数", "Available to sell"), amount(p.sellable, 0))}
      ${metric(say("账户占比", "Portfolio weight"), amount(p.weight_pct) + "%")}
      ${metric(say("含费均价", "Avg. cost incl. fees"), amount(p.avg_cost, 4))}
      ${metric(say("保本卖出报价", "Break-even sell quote"), yuan(p.break_even_quote))}
      ${metric(say("全仓卖出预计净盈亏", "Net P&L if liquidated"), yuan(p.exit_net_pnl), p.exit_net_pnl)}</dl>
      ${note(say("估值参考", "Valuation mark") + " " + yuan(p.price) + " · " + time(p.quote_asof) + (p.valuation_source === "last_trade_quote" ? " · " + say("沿用上次模拟成交参考价", "Last paper fill’s reference quote") : ""))}`
      : note(say("尚未持有这只股票。", "You have no paper position in this stock."));
    const quote = b.quote;
    el("paper-quote").textContent = [
      say("参考报价", "Reference quote") + " " + yuan(quote?.price),
      quote?.source, quote?.asof && time(quote.asof),
      !b.can_trade && translate(b.trade_reason || say("当前仅可测算", "Preview only")),
    ].filter(Boolean).join(" · ");
    el("paper-records").innerHTML = holdingsAndFills(b, ctx.stock);
  }
  function table(headers, rows) {
    return `<div class="table-scroll"><table><thead><tr>${headers.map((h) => `<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function holdingsAndFills(book, stock) {
    const name = (row) => language() === "en"
      ? (row.symbol === stock.id && stock.english) || row.symbol?.toUpperCase() : row.name || row.symbol;
    const symbol = say("股票", "Stock");
    const shares = say("股数", "Shares");
    const holdings = book.positions || [];
    const fills = book.history || [];
    return `<dl class="paper-metrics">${metric(say("初始资金", "Starting cash"), yuan(book.initial_cash))}
      ${metric(say("持仓市值", "Holdings value"), yuan(book.market_value))}
      ${metric(say("预计清仓后权益", "Est. liquidation equity"), yuan(book.net_liquidation_equity))}</dl>
      <h4>${say("全部持仓", "All holdings")}</h4>${holdings.length ? table([symbol, shares, say("可卖", "Sellable"), say("浮动盈亏", "Unrealized P&L"), say("估值时点", "Mark time")],
      holdings.map((r) => [name(r), amount(r.quantity, 0), amount(r.sellable, 0), yuan(r.unrealized_pnl), time(r.quote_asof)])) : note(say("暂无持仓", "No open positions"))}
      <h4>${say("近期成交", "Recent fills")}</h4>${fills.length ? table([say("成交时间", "Filled at"), symbol, say("方向", "Side"), shares, say("模拟成交价", "Fill price"), say("滑点金额", "Slippage"), say("税费合计", "Fees & taxes"), say("资金变动", "Cash change")],
      fills.map((r) => [time(r.executed_at), name(r), sideName(r.side), amount(r.quantity, 0), yuan(r.fill_price), yuan(r.slippage), yuan(r.fees), yuan(r.cash_delta)])) : note(say("暂无成交记录", "No fills yet"))}`;
  }
  async function load(ctx) {
    if (ctx !== active) return;
    if (ctx.reading) { ctx.reloadRequested = true; return; }
    ctx.reading = true;
    controls(ctx);
    try {
      const book = await request("", {symbol: ctx.stock.id});
      if (ctx !== active) return;
      if (!Array.isArray(book.positions) || !Array.isArray(book.history) || !Number.isFinite(book.cash))
        throw Error(say("模拟账户数据不完整", "Incomplete paper account response"));
      const previous = ctx.book;
      const changed = previous && (previous.cash !== book.cash ||
        previous.history[0]?.request_id !== book.history[0]?.request_id);
      if (changed) { invalidateReview(ctx); drawReview(ctx); }
      if (ctx.pending && book.history.some((r) => r.request_id === ctx.pending.request_id)) {
        remember(ctx, null);
        clearPreview(ctx);
        message(say("已核对，原委托已成交。", "The original paper order was filled."));
      }
      if (ctx.stale) message("");
      ctx.book = book;
      if (!book.can_trade) ctx.canTrade = false;
      ctx.stale = false;
      drawBook(ctx);
    } catch (error) {
      if (ctx === active) {
        ctx.stale = true;
        message(say("账户刷新失败", "Account refresh failed") + " · " + error.message, true);
      }
    } finally {
      if (ctx === active) {
        ctx.reading = false;
        controls(ctx);
        if (ctx.reloadRequested) { ctx.reloadRequested = false; load(ctx); }
      }
    }
  }
  function clearPreview(ctx) {
    ctx.preview = null;
    el("paper-estimate").replaceChildren();
  }
  async function preview(ctx) {
    const quantity = el("paper-qty").valueAsNumber;
    if (ctx.busy || ctx.pending || !Number.isSafeInteger(quantity) || quantity < 1) return;
    ctx.side = el("paper-side").value;
    ctx.busy = true;
    clearPreview(ctx);
    message(say("正在测算…", "Calculating…"));
    controls(ctx);
    try {
      const result = await request("/preview", {}, post({symbol: ctx.stock.id, side:ctx.side, quantity}));
      if (active !== ctx) return;
      const p = result.preview;
      if (!p || !Number.isFinite(p.quote_price)) throw Error(say("预览缺少有效报价", "No valid quote in preview"));
      ctx.preview = p;
      ctx.canTrade = result.can_trade;
      el("paper-estimate").innerHTML = `<dl class="paper-metrics">
        ${metric(say("成交参考报价", "Execution reference"), yuan(p.quote_price))}
        ${metric(say("含滑点成交价", "Slippage-adjusted fill"), yuan(p.fill_price))}
        ${metric(say("滑点金额", "Slippage amount"), yuan(p.slippage))}
        ${metric(say("佣金", "Commission"), yuan(p.commission))}
        ${metric(say("过户费", "Transfer fee"), yuan(p.transfer_fee))}
        ${metric(say("印花税", "Stamp tax"), yuan(p.stamp_tax))}
        ${metric(say("资金变动", "Cash change"), yuan(p.cash_delta))}
        ${metric(say("预计现金余额", "Cash after fill"), yuan(p.cash_after))}</dl>
        ${p.quote_asof ? note(say("测算报价时间", "Quote used for this estimate") + " · " + time(p.quote_asof)) : ""}`;
      message(result.can_trade ? say("请核对费用后确认。", "Review costs before confirming.")
        : translate(result.trade_reason || say("仅供盘后测算。", "For estimation only.")));
    } catch (error) {
      if (active === ctx) message(error.message, true);
    } finally {
      if (active === ctx) {ctx.busy = false; controls(ctx);}
    }
  }
  async function execute(ctx) {
    if (ctx.busy || (!ctx.pending && !ctx.preview)) return;
    const p = ctx.preview;
    const order = ctx.pending || {symbol:ctx.stock.id, side:p.side, quantity:p.quantity,
      expected_price:p.quote_price, request_id:crypto.randomUUID()};
    remember(ctx, order);
    ctx.busy = true;
    controls(ctx);
    message(say("正在核对并提交模拟委托…", "Checking and submitting paper order…"));
    try {
      const result = await request("/orders", {}, post(order));
      if (result.order?.request_id !== order.request_id)
        throw Error(say("成交回执待核对", "Fill receipt needs reconciliation"));
      remember(ctx, null);
      if (ctx !== active) return;
      clearPreview(ctx);
      invalidateReview(ctx);
      drawReview(ctx);
      message(say("模拟成交", "Paper fill") + " · " + sideName(order.side) + " " + amount(order.quantity, 0) + " @ " + yuan(result.order.fill_price));
    } catch (error) {
      if (error.status >= 400 && error.status < 500) {
        remember(ctx, null);
        if (ctx === active) {clearPreview(ctx); message(error.message, true);}
      } else if (ctx === active) {
        message(say("尚未收到成交回执。刷新账户或重试原委托以核对结果。", "Fill status unknown. Refresh the account or retry the original order to reconcile."), true);
      }
    } finally {
      if (ctx === active) {
        ctx.busy = false;
        controls(ctx);
        load(ctx);
      }
    }
  }
  function reviewWaiting(ctx) {
    return ["queued", "running"].includes(ctx.review?.status);
  }
  function drawReview(ctx) {
    const r = ctx.review;
    const out = el("paper-advice");
    el("paper-review").textContent = say("复核当前仓位", "Review position") + ` · ${ctx.horizon} ` + say("日", "d");
    if (!r) {out.replaceChildren(); controls(ctx); return;}
    const fallback = {queued:say("等待模型复核", "Queued"), running:say("复核中", "Review in progress"),
      disabled:say("当前已关闭模型复核", "Model review is turned off")};
    out.innerHTML = [r.status === "ready" && r.decision, r.summary, r.risk, r.message || fallback[r.status]]
      .filter(Boolean).map((s) => `<p>${esc(translate(s))}</p>`).join("")
      + note([r.model, r.updated_at && time(r.updated_at), r.refs?.join(" · ")].filter(Boolean).join(" · "));
    controls(ctx);
  }
  function pollReview(ctx) {
    clearTimeout(ctx.timer);
    ctx.timer = setTimeout(() => {
      if (ctx === active && expanded && !document.hidden) review(ctx, false);
      else if (ctx === active && expanded) pollReview(ctx);
    }, 3500);
  }
  async function review(ctx, start) {
    if (ctx.reviewBusy) return;
    const seq = ++ctx.reviewSeq;
    ctx.reviewBusy = true;
    controls(ctx);
    if (start) el("paper-advice").textContent = say("正在提交仓位复核…", "Requesting position review…");
    const fields = {symbol:ctx.stock.id, horizon:ctx.horizon, lang:language()};
    try {
      const result = start ? await request("/review", {}, post(fields)) : await request("/review", fields);
      if (ctx !== active || seq !== ctx.reviewSeq) return;
      ctx.review = result.review;
      drawReview(ctx);
      if (expanded && reviewWaiting(ctx)) pollReview(ctx);
    } catch (error) {
      if (ctx === active && seq === ctx.reviewSeq) {
        ctx.review = null;
        el("paper-advice").textContent = error.message;
      }
    } finally {
      if (ctx === active && seq === ctx.reviewSeq) {ctx.reviewBusy = false; controls(ctx);}
    }
  }
  host.addEventListener("submit", (e) => {
    if (e.target.id === "paper-form") {e.preventDefault(); if (active) preview(active);}
  });
  host.addEventListener("input", (e) => {
    if (!active || !["paper-side", "paper-qty"].includes(e.target.id)) return;
    clearPreview(active);
    message("");
    controls(active);
  });
  host.addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!active || !btn || btn.disabled) return;
    if (btn.id === "paper-confirm") execute(active);
    if (btn.id === "paper-refresh") load(active);
    if (btn.id === "paper-review") review(active, true);
  });
  window.addEventListener("model-settings-changed", () => {
    if (active) {invalidateReview(active); drawReview(active);}
  });
  setInterval(() => {
    if (active && expanded && !active.busy && !document.hidden && el("auto")?.checked) load(active);
  }, 30000);
  window.LilacPaper = {select, costExample};
})();
