(() => {
  "use strict";
  const host = document.getElementById("replay-workspace");
  const en = window.LilacI18n.lang === "en";
  const t = (zh, eng) => en ? eng : zh;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (char) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[char]);
  const num = (n, digits = 0) => Number.isFinite(n)
    ? n.toLocaleString(en ? "en-US" : "zh-CN", {minimumFractionDigits:digits, maximumFractionDigits:digits}) : "—";
  const pct = (n, signed = false) => Number.isFinite(n) ? `${signed && n > 0 ? "+" : ""}${num(100 * n, 2)}%` : "—";
  const names = {price:t("只看走势", "Price signals"), evidence:t("走势＋情报", "Price + evidence"),
    ai:t("走势＋情报＋AI", "With AI review"), hold:t("买入并持有", "Buy and hold")};
  let active = null;
  let saving = false;

  function setup(ctx) {
    const stockName = (en ? ctx.stock.english || ctx.stock.code : ctx.stock.name) || ctx.stock.id;
    host.innerHTML = `<div class="panel-top replay-head"><div><h2 id="replay-title" class="panel-title">${t("策略复盘", "Strategy replay")}</h2>
      <p class="note">${esc(stockName)} · ${t("按当时的 5 日信号模拟交易，比较扣费后的收益。", "Compare returns after costs from trading this stock’s 5-day signals as they arrived.")}</p></div>
      <button id="replay-refresh" type="button" class="paper-button">${t("刷新复盘", "Refresh replay")}</button></div>
      <div id="replay-result"></div><p id="replay-status" class="paper-feedback" role="status"></p>`;
  }

  function select(stock) {
    if (stock && active?.stock.id === stock.id) return;
    active = null;
    host.hidden = !stock;
    host.replaceChildren();
    if (!stock) return;
    const ctx = active = {stock, data:null, group:null, read:0};
    setup(ctx);
    load(ctx);
  }

  function setStatus(message, error = false) {
    const status = document.getElementById("replay-status");
    status.textContent = message;
    status.classList.toggle("error", error);
  }

  async function load(ctx) {
    const seq = ++ctx.read;
    const button = document.getElementById("replay-refresh");
    button.disabled = true;
    if (!ctx.data) setStatus(t("正在读取复盘记录…", "Loading replay records…"));
    try {
      const response = await fetch("/api/replay?" + new URLSearchParams({symbol:ctx.stock.id}),
        {cache:"no-store", signal:AbortSignal.timeout(20000)});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      const report = await response.json();
      if (!report.common || !report.paired) throw Error(t("记录格式异常", "Incomplete replay records"));
      if (ctx !== active || ctx.read !== seq) return;
      ctx.data = report;
      draw(ctx);
      setStatus("");
    } catch (err) {
      if (ctx === active && ctx.read === seq) setStatus(t("读取失败，可点击「刷新复盘」重试。", "Couldn’t load records. Select Refresh replay to retry.") + " " + err.message, true);
    } finally {
      if (ctx === active && ctx.read === seq) button.disabled = saving;
    }
  }

  function emptyState(ctx, group) {
    const data = ctx.data;
    if (!data.signals && data.eligibility === "unvalidated") return t("这只股票还没有可核验的 5 日预测样本，新上市股票常会遇到这种情况。可以先看走势和公司资料，积累足够的交易日后会自动开始记录。", "This stock does not yet have a verifiable 5-day forecast sample. This is common for new listings. You can explore its chart and company information while more trading days accumulate.");
    if (!data.signals && data.eligibility === "history") return t("当前缺少可用的前复权日线。历史数据补齐后，程序才能为这只股票记录可比较的信号。", "Usable adjusted daily prices are missing. Recording can begin once the stock’s price history becomes available.");
    if (!data.signals && data.eligibility === "stale") return t("行情与最新收盘日线尚未核对。保持程序运行，等两者更新后再记录本期信号。", "The quote and latest daily close have not yet been matched. Leave the app running so it can record the signal when both update.");
    if (!data.signals) return t("还没有收盘记录。收盘后保持本机程序运行，它会为这只自选股保存当天的信号。", "No closing signal yet. Leave the app running after the close to record this watchlist stock’s signal.");
    if (group === "common" && data.paired.samples) return t("已有量化记录，暂时没有同时取得 AI 复核和后续报价的日期。可以先看「全部量化记录」。", "Quantitative results are available. No date has both a timely AI review and a later quote yet. Select All quant records to see them.");
    if (data.pending) return t("已保存收盘信号。下一交易时段采到可用报价后，就能看到这次模拟结果。", "A closing signal is saved. Its result will appear when a usable quote is observed in the next trading session.");
    return t("还没有可比较的成交日。收盘后和次日盘中保持程序运行，错过的报价会留空。", "No comparable execution date yet. Leave the app running after the close and during the next session to collect both observations.");
  }

  function table(rows, columns) {
    return `<div class="table-scroll"><table><thead><tr><th scope="col">${t("策略", "Strategy")}</th>${columns.map(c => `<th scope="col">${c[0]}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(row => `<tr><th scope="row">${esc(names[row.key] || row.key)}</th>${columns.map(c => `<td>${esc(c[1](row))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function latestActions(cohort) {
    if (!cohort.recent?.length) return "";
    const labels = {buy:t("买入", "Bought"), sell:t("卖出", "Sold"), hold:t("继续持有", "Held"),
      cash:t("持币", "Stayed in cash"), unfilled:t("未成交", "Unfilled")};
    const keys = cohort.rows.map(row => row.key);
    return `<h3 class="replay-subtitle">${t("最近怎样操作？", "What did each strategy do?")}</h3>
      <div class="table-scroll"><table><thead><tr><th scope="col">${t("观察日", "Quote date")}</th>
      ${keys.map(key => `<th scope="col">${esc(names[key])}</th>`).join("")}</tr></thead>
      <tbody>${cohort.recent.map(day => `<tr><th scope="row">${esc(day.day)}</th>
      ${keys.map(key => `<td>${esc(labels[day.actions?.[key]] || "—")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function comparison(ctx, group) {
    const cohort = ctx.data[group];
    if (!cohort.samples) return `<p class="replay-empty">${emptyState(ctx, group)}</p>`;
    const rows = cohort.rows;
    const date = cohort.from === cohort.through ? cohort.through : `${cohort.from} – ${cohort.through}`;
    const subject = group === "common" ? "ai" : "evidence";
    const base = group === "common" ? "evidence" : "price";
    const returns = Object.fromEntries(rows.map(r => [r.key, r.net_return]));
    let lead = "";
    if (Number.isFinite(returns[subject]) && Number.isFinite(returns[base])) {
      const gap = (returns[subject] - returns[base]) * 100;
      const label = group === "common" ? t("加入 AI 复核后", "Adding AI review") : t("加入情报后", "Adding evidence");
      const delta = num(Math.abs(gap), 2);
      lead = Math.abs(gap) < .005 ? t(`${label}，这段时间的净收益持平。`, `${label} left net returns unchanged to two decimals.`)
        : t(`${label}，这段时间的净收益${gap > 0 ? "高" : "低"}了 ${delta} 个百分点。`, `${label} ${gap > 0 ? "raised" : "lowered"} net returns by ${delta} percentage points over this period.`);
    }
    return `<p class="replay-interval">${esc(date)} · ${t(`有 ${num(cohort.samples)} 个可比交易日`, `${num(cohort.samples)} comparable trading ${cohort.samples === 1 ? "day" : "days"}`)}</p>
      ${lead ? `<p class="replay-insight">${esc(lead)}</p>` : ""}
      ${table(rows, [[t("扣费后收益", "Net return"), r => pct(r.net_return, true)], [t("最大回撤", "Max. drawdown"), r => pct(r.max_drawdown)]])}
      <p class="note">${t("最大回撤是这段时间内，账户从高点到后续低点的最大跌幅。", "Drawdown is the largest drop from a previous account high during this period.")}</p>
      <details class="replay-detail" data-replay-detail="trading"><summary>${t("查看交易记录与费用", "See trading activity and costs")}</summary>
      ${table(rows, [[t("成交笔数", "Fills"), r => num(r.trades)], [t("未成交", "Unfilled"), r => num(r.unfilled)], [t("换手率", "Turnover"), r => pct(r.turnover)], [t("税费（元）", "Fees & tax (CNY)"), r => num(r.fees, 2)]])}
      ${latestActions(cohort)}</details>`;
  }

  function draw(ctx) {
    const data = ctx.data;
    const group = ctx.group || (data.common.samples ? "common" : "paired");
    const open = [...host.querySelectorAll("details[open]")].map(node => node.dataset.replayDetail);
    const focused = host.contains(document.activeElement) ? document.activeElement.id : "";
    const tab = (key, label) => `<button type="button" id="replay-${key}" data-replay-group="${key}" aria-pressed="${key === group}">${label}</button>`;
    const stats = [
      t(`已记录 ${num(data.signals)} 天信号`, `${num(data.signals)} recorded signals`),
      t(`${num(data.pending)} 天待报价`, `${num(data.pending)} awaiting a quote`),
      t(`${num(data.missed)} 天错过报价`, `${num(data.missed)} missed quotes`),
      data.last_origin && t(`最近信号 ${data.last_origin}`, `Latest signal ${data.last_origin}`),
    ].filter(Boolean).join(" · ");
    const restartReasons = {
      price_basis_changed:t("前收价格基准变化", "the prior-close price basis changed"),
      missing_reference:t("缺少可核对的前收价", "a comparable prior close was unavailable"),
      observation_gap:t("交易报价出现间隔", "there was a gap in observed quotes"),
    };
    const restart = restartReasons[data.restart_reason] || t("无法连续比较报价", "the quotes could not be compared continuously");
    document.getElementById("replay-result").innerHTML = `
      <div class="replay-groups" role="group" aria-label="${t("比较范围", "Comparison dates")}">
      ${tab("paired", t("全部量化记录", "All quant records"))}
      ${tab("common", t("含 AI 的共同日期", "Dates with AI review"))}</div>
      ${data.earlier_samples ? `<p class="note">${esc(t(`因${restart}，两组从 ${data.segment_start} 按初始资金重新计算。此前 ${num(data.earlier_samples)} 条报价记录已保留。`, `Both groups restart with their initial cash on ${data.segment_start} because ${restart}. The archive holds ${num(data.earlier_samples)} earlier ${data.earlier_samples === 1 ? "quote" : "quotes"}.`))}</p>` : ""}
      <div id="replay-comparison">${comparison(ctx, group)}</div>
      <details class="replay-detail" data-replay-detail="method"><summary>${t("怎样得到这些结果？", "How are results calculated?")}</summary>
        <p>${esc(stats)}</p><p>${t("每种策略各用", "Each strategy starts with")} ¥${num(data.initial_cash)}${t(" 模拟资金。在同一组日期用相同报价，计入滑点和交易税费，期末再扣除预计卖出成本。两个日期分组分别起算。", " in paper cash. Strategies within a date group use the same quotes, slippage and fees. Ending values include estimated selling costs. Each date group starts fresh.")}</p>
        <p>${t("前两种策略在 5 日信号偏强且预计扣费后盈利时买入，其余时间持币。AI 可沿用策略、暂缓加仓或退出。买入并持有用作参照。", "The first two strategies buy when their 5-day signal is bullish and expected gains cover costs. Otherwise they hold cash. AI can follow the signal, hold off adding, or exit. Buy and hold is the reference.")}</p>
        <p>${t("使用信号记录后，下一工作日连续竞价时段实际采到的第一笔报价尝试交易。共同日期组只在有及时 AI 复核时交易，中间的有效报价仍用于持仓估值。", "Orders use the first observed continuous-session quote on the next weekday. In the AI group, trades require a timely review. Any quotes observed in between are still used to value open positions.")}</p>
      </details>
      <div class="replay-automation"><label><input type="checkbox" id="replay-auto" aria-describedby="replay-auto-help" ${data.auto_ai ? "checked" : ""} ${saving ? "disabled" : ""}>
      ${t("收盘后自动请 AI 复核全部自选股", "Request after-close AI reviews for all watchlist stocks")}</label>
      <p id="replay-auto-help" class="note">${data.model_enabled
        ? t("启用后会使用所选模型的额度。关闭时，仍会收录及时完成的普通研究复核。", "Enabling this uses your selected model’s quota. Timely reviews from ordinary research still count when this is off.")
        : t("模型设置目前为「仅量化」，量化复盘会照常记录。启用模型后，后台复核会使用所选模型的额度。", "Model settings are on Quant only. Quant records continue. Once a model is enabled, background reviews use that model’s quota.")}</p></div>`;
    for (const node of host.querySelectorAll("details")) if (open.includes(node.dataset.replayDetail)) node.open = true;
    if (focused && !document.activeElement.id) document.getElementById(focused)?.focus({preventScroll:true});
  }

  async function saveSetting(ctx, input) {
    if (saving) return;
    saving = true;
    input.disabled = true;
    const desired = input.checked;
    ++ctx.read;
    document.getElementById("replay-refresh").disabled = true;
    setStatus(t("正在保存…", "Saving…"));
    let error = "";
    try {
      const response = await fetch("/api/replay/settings", {method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({auto_ai:desired}), signal:AbortSignal.timeout(20000)});
      if (!response.ok) throw Error(`HTTP ${response.status}`);
      ctx.data.auto_ai = desired;
    } catch (err) {
      error = t("无法确认设置是否保存，请刷新复盘核对。", "Couldn’t confirm the change. Refresh the replay to check.") + " " + err.message;
    } finally {
      saving = false;
      if (ctx === active) {
        draw(ctx);
        document.getElementById("replay-refresh").disabled = false;
        document.getElementById("replay-auto").focus({preventScroll:true});
        setStatus(error || t("已保存自选股复核设置。", "Watchlist review preference saved."), !!error);
      } else if (active) load(active);
    }
  }
  host.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!active || !button) return;
    if (button.id === "replay-refresh") load(active);
    if (button.dataset.replayGroup && active.data) {
      active.group = button.dataset.replayGroup;
      draw(active);
    }
  });
  host.addEventListener("change", (event) => {
    if (event.target.id === "replay-auto" && active) saveSetting(active, event.target);
  });
  function refresh() {
    if (active && !saving && !document.getElementById("replay-refresh").disabled) load(active);
  }
  window.addEventListener("model-settings-changed", refresh);
  window.LilacReplay = {select, refresh};
})();
