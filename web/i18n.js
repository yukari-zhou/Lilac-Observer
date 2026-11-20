(() => {
  "use strict";
  const key = "lilac-observer-language";
  const url = new URL(location.href);
  const requested = url.searchParams.get("lang");
  let stored;
  try { stored = localStorage.getItem(key); } catch {}
  const lang = (["en", "zh"].includes(requested) ? requested : stored) === "en" ? "en" : "zh";
  if (requested === "en" || requested === "zh") {
    try { localStorage.setItem(key, lang); } catch {}
  }

  // The Chinese strings are also the source-language UI. Match complete labels or
  // known templates so company names and third-party reporting retain their wording.
  const messages = new Map(`
跳至研究内容|Skip to research
Lilac-Observer · A 股研究台|Lilac-Observer · A-share research
Lilac-Observer 研究台首页|Lilac-Observer home
主导航|Main navigation
北京时间|China Standard Time
研究终端|Terminal
因子与情报|Factors & evidence
历史验证|Validation
A 股研究台|A-share research
模型设置|Model settings
自动刷新|Auto-refresh
刷新数据|Refresh
标的类型|Instrument type
市场指数|Indices
自选股|Watchlist
搜索上市公司|Search listed companies
搜索股票名称或代码|Search by company or ticker
选择研究标的|Select an instrument
当前研究|Current research
正在读取行情…|Loading market data…
所有时间均为北京时间|All times in China Standard Time
移出自选|Remove from watchlist
交易日周期|Trading sessions
数据与方法说明|Data and methodology
预测方法与验证边界|Forecast methodology and validation limits
关闭模型设置|Close model settings
选择用于复核量化结果、财报与市场情报的模型。|Choose a model to review forecasts, filings and market evidence.
接入方式|Connection
兼容 API|Compatible API
仅量化|Quantitative only
Codex 模型|Codex model
可选|Optional
使用 Codex 默认模型|Use the default Codex model
API 地址|API base URL
支持 Chat Completions 兼容服务和本机推理服务。|Supports Chat Completions-compatible services and local models.
模型 ID|Model ID
填写服务端提供的模型名称|Enter your provider’s model ID
API 密钥|API key
按服务要求填写|If required by your provider
清除已保存密钥|Clear saved key
行情摘要与证据将发送至所填服务，设置保存在本机。|Market summaries and evidence go to this service. Settings are saved locally.
继续计算量化因子、走势区间和风险参考，暂停 AI 复核。|Factors, price ranges and risk levels remain available with AI review off.
当前启用离线模式。恢复联网模式后，所选模型可参与复核。|Offline mode is active. Enable networking to use model review.
当前服务通过环境变量关闭了 AI 复核。调整环境变量并重启服务后可启用复核。|AI review is disabled by an environment variable. Update it and restart the service to enable review.
重新读取|Reload
取消|Cancel
保存设置|Save settings
留空以保留现有密钥|Leave blank to keep the current key
输入 API 密钥|Enter API key
已更换地址，如需认证请填写新服务的密钥|The endpoint changed. Enter its API key if required.
本机已保存密钥|Key saved locally
使用环境变量中的密钥|Using a key from the environment
当前未配置密钥|No key configured
已找到本机 Codex CLI，将使用其登录状态。|Codex CLI found. The terminal uses its local sign-in.
未找到本机 Codex CLI，选择此方式前请安装并登录 Codex。|Install Codex CLI and sign in before choosing this mode.
正在读取本机设置…|Loading local settings…
请填写服务端提供的模型 ID。|Enter the model ID from your provider.
正在保存…|Saving…
服务返回的模型设置无效|Invalid model settings response
股票行情与走势|Stock price and chart
指数行情与走势|Index level and chart
选择要查看的股票|Choose a stock
自选股列表为空|Your watchlist is empty
通过名称或代码搜索公司，即可加入并查看股价走势。|Find a company by name or ticker to add it and view its chart.
搜索股票|Find a stock
未找到匹配的 A 股上市公司。可尝试证券简称或六位代码。|No A-share listing matched. Try a short name or six-digit ticker.
暂无 A 股上市行情|No A-share quote available
查看来源|View source
查看走势|Open chart
＋ 加入自选|＋ Watch
正在检索上市公司…|Searching listed companies…
正在加入自选…|Adding stock…
正在更新自选…|Updating watchlist…
自选列表数据不完整|Incomplete watchlist response
此证券尚未加入本机自选。请核对搜索结果后加入。|This stock is outside your watchlist. Check the search result to add it.
上证指数|SSE Composite
深证成指|SZSE Component
沪深300|CSI 300
沪深 300|CSI 300
创业板指|ChiNext
上证50|SSE 50
中证500|CSI 500
历史收盘|Historical close
盘中行情|Live quote
最近报价|Latest quote
来源延迟|Delayed
缓存行情|Cached quote
历史快照|Snapshot
暂无报价|No quote
暂无当日成交|No trades today
开盘|Open
最高|High
最低|Low
收盘|Close
昨收|Previous close
行情时间|Quote time
收盘日期|Close date
分时股价|Intraday price
收盘走势|Closing price
波动参考|Volatility range
期末区间|Forecast range
走势图周期|Chart range
1月|1M
3月|3M
6月|6M
1年|1Y
全部|All
分时|Intraday
暂无分时数据|No intraday data
暂无收盘日线|No daily closes
前复权日线|Adjusted daily prices
元|CNY
点|pts
尚未取得该股的分时成交记录|No intraday trades available
尚无可绘制的收盘日线|No closing prices to plot
趋势研判|Outlook
历史复盘|Historical review
收盘模型|Close-based model
预测交易日|Horizon
预测周期|Forecast horizon
综合因子分|Factor score
数据不足|Insufficient data
偏强|Bullish
震荡|Rangebound
中性|Neutral
偏弱|Bearish
样本待积累|Awaiting validation
期末情景股价（元）|Terminal share price (CNY)
期末情景点位|Terminal index level
波动参考区间（元）|Volatility range (CNY)
波动参考区间（点）|Volatility range (pts)
下沿|Lower
中枢|Central
上沿|Upper
条件策略|Conditional strategy
等待有效数据后生成策略。|Waiting for usable data.
模型因子|Model factors
因子贡献|Factor contributions
全部因子|All factors
因子|Factor
方向强度|Signal strength
得分|Score
权重|Weight
本次计算缺少有效因子|No eligible factors for this calculation
策略与风控|Strategy & risk
风险阈值|Risk threshold
止损条件|Stop condition
触发条件|Entry trigger
仓位参考|Position guidance
复核|Reassess
AI 复核|AI review
分析中|Analyzing
排队中|Queued
研判完成|Reviewed
量化模式|Quantitative only
模型不可用|Model unavailable
依据不足|Insufficient evidence
待更新|Pending
风险观察|Risk to monitor
等待当前研究结果。|Waiting for research.
M 量化模型|M Quantitative model
Q 行情|Q Quote
成份股|Constituent
行业|Sector
指数权重|Index weight
营收同比|Revenue growth YoY
净利同比|Profit growth YoY
报告期|Reporting period
披露日|Disclosure date
权重来源|Weight source
查看公司财报|Company financials
所属行业待补充|Sector unavailable
财报原文|Original filing
指标|Metric
当期金额|Amount
同比|YoY
营业收入|Revenue
归母净利润|Profit attributable to shareholders
当期情报与基本面|Evidence & fundamentals
全市场|Market-wide
来源资料|Source
当前数据源暂无可用于该标的的情报|No eligible evidence for this instrument.
滚动样本外验证|Walk-forward validation
历史样本|Historical observations
已实现的预测结果|Matured forecasts
模型方向命中率|Model direction accuracy
预测与实际涨跌方向一致|Forecast direction matched the outcome
方向基准命中率|Benchmark direction accuracy
同一样本的基准结果|Benchmark on the same observations
预测平均绝对误差|Model mean absolute error
收益率的绝对偏差|Absolute return error
基准平均绝对误差|Benchmark MAE
同一样本的预测基准|Benchmark on the same forecasts
区间覆盖率|Range coverage
期末实现在预测区间内|Terminal close inside the forecast range
当前样本不足以验证模型表现。|Too few observations to validate the model.
前向跟踪|Forward tracking
沿用量化策略|Follow the quantitative strategy
继续观察|Wait
防守|Defensive
待核验|Pending
已核验|Settled
方向命中率|Direction accuracy
起算日|Origin date
签发时间|Issued at
周期|Horizon
预测方向|Direction
复核策略|Reviewed strategy
状态|Status
实际涨跌|Realized return
当前标的和周期暂无已登记的预测。|No forecasts recorded for this instrument and horizon.
本次响应未包含前向跟踪记录。|No forward-tracking records returned.
正在读取行情并计算预测…|Loading quotes and calculating the forecast…
暂时无法读取研究数据|Research data unavailable
请检查本地服务是否运行，再重新获取行情。|Check that the local service is running, then try again.
重新加载|Retry
刷新失败，当前展示上一次取得的研究结果。|Refresh failed. Showing the last available research.
研究结果字段不完整|Incomplete research response
暂无可选指数|No indices available
请求超时|Request timed out
报价|Quote
日线|Daily bars
腾讯财经|Tencent Finance
新浪财经|Sina Finance
东方财富|Eastmoney
暂无|Unavailable
新闻|News
政策|Policy
情绪|Sentiment
市场广度|Market breadth
基本面|Fundamentals
宏观|Macro
公司公告|Company filing
情报|Evidence
`.trim().split("\n").map(line => line.split("|")));

  const patterns = [
    [/^(\d+) 日$/, "$1D"], [/^\+(\d+)日$/, "+$1D"], [/^未来 (\d+) 个交易日$/, "Next $1 trading sessions"],
    [/^基于 (.+) 收盘$/, "From the $1 close"], [/^(\d+) 个交易日$/, "$1 trading sessions"],
    [/^共 (\d+) 个收盘交易日$/, "$1 daily closes"], [/^(\d+) 项$/, "$1 factors"], [/^(\d+) 条证据$/, "$1 sources"],
    [/^(.*?)（(\d+)）$/, (_, text, count) => translate(text) + " (" + count + ")"],
    [/^行情时间 (.+)$/, (_, stamp) => "Quote at " + translate(stamp)], [/^收盘日期 (.+)$/, "Close on $1"],
    [/^(报价|日线) (.+)$/, (_, label, source) => (label === "报价" ? "Quote: " : "Daily bars: ") + translate(source)],
    [/^(.+?) · 模型权重 (.+)$/, (_, group, weight) => translate(group) + " · Model weight " + weight],
    [/^(.+)已加入自选$/, "$1 added to watchlist"], [/^(.+)已移出自选$/, "$1 removed from watchlist"],
    [/^移除(.+)$/, "Remove $1"], [/^将(.+)移出自选$/, "Remove $1 from watchlist"],
    [/^([\d,.-]+) 元$/, "$1 CNY"], [/^([\d,.-]+) 点$/, "$1 pts"], [/^([\d,.-]+) 亿元$/, "$1 × 100m CNY"],
    [/^查看 (\d+) 家成份股财报与权重$/, "Financials and weights of $1 constituents"],
    [/^记录在下一交易日开盘前首次完成的模型复核结果，按第 (\d+) 个交易日的实际收盘核验。方向命中按期末情景中枢相对于起算收盘的涨跌方向计算。$/, "The first review before the next open is scored against the close after $1 sessions. Direction compares the forecast midpoint with the origin close."],
    [/^收盘走势，(.+) 至 (.+)。使用左右方向键查看逐日行情。$/, "Daily closes, $1 to $2. Use arrow keys to inspect."],
    [/^(.+) 分时股价，(.+) 至 (.+)。使用左右方向键查看记录。$/, "Intraday prices for $1, $2 to $3. Use arrow keys to inspect."],
    [/^股价 (.+) 元$/, "Price $1 CNY"], [/^收盘 ([\d,.]+)$/, "Close $1"], [/^低 (.+) · 高 (.+)$/, "Low $1 · High $2"],
    [/^E(\d+) · (.+)$/, (_, id, category) => "E" + id + " · " + translate(category)],
    [/^量化策略：(.+)$/, (_, policy) => "Quantitative strategy: " + translate(policy)],
    [/^(自选更新失败|数据请求失败|证券目录未就绪|设置请求失败)（(.+)）$/, (_, kind, detail) => ({"自选更新失败":"Watchlist update failed","数据请求失败":"Data request failed","证券目录未就绪":"Directory unavailable","设置请求失败":"Settings request failed"}[kind]) + " (" + translate(detail) + ")"],
    [/^检索失败，(.+)。请重新搜索。$/, (_, detail) => "Search failed: " + translate(detail) + ". Try again."],
    [/^(研究生成|更新|模型|权重日期|报告期|披露日|依据|已覆盖行业|计分依据)[\s　]+(.+)$/, (_, key, val) => ({"研究生成":"Research generated","更新":"Updated","模型":"Model","权重日期":"Weights as of","报告期":"Reporting period","披露日":"Disclosed","依据":"Evidence","已覆盖行业":"Covered sectors","计分依据":"Scoring basis"}[key]) + " " + translate(val)]
  ];
  function translate(source) {
    if (lang !== "en" || typeof source !== "string" || !/[\u3400-\u9fff]/.test(source)) return source;
    const text = source.trim();
    let value = messages.get(text);
    if (value === undefined) {
      for (const [pattern, replacement] of patterns) {
        if (pattern.test(text)) { value = text.replace(pattern, replacement); break; }
      }
    }
    if (value === undefined && text.includes(" · ")) value = text.split(" · ").map(translate).join(" · ");
    return value === undefined ? source : source.replace(text, () => value);
  }
  window.LilacI18n = {lang, translate, add(entries, rules = []) {
    for (const [source, target] of entries) messages.set(source, target);
    patterns.unshift(...rules);
  }};
  const toggle = document.getElementById("lang-switch");
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  if (lang === "en") {
    toggle.textContent = "中文"; toggle.lang = "zh-CN"; toggle.setAttribute("aria-label", "切换为中文");
  }
  toggle.addEventListener("click", () => {
    const next = lang === "en" ? "zh" : "en";
    try { localStorage.setItem(key, next); } catch {}
    const address = new URL(location.href);
    address.searchParams.set("lang", next);
    location.assign(address.href);
  });
  if (lang === "en") {
    const attrs = ["aria-label", "placeholder", "title"];
    function localize(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.parentElement?.closest("script, style, #lang-switch, [data-original]")) return;
        const value = translate(node.nodeValue);
        if (value !== node.nodeValue) node.nodeValue = value;
      } else if (node.nodeType === Node.ELEMENT_NODE && !node.matches("script, style, #lang-switch, [data-original]")) {
        for (const attr of attrs) if (node.hasAttribute(attr)) {
          const source = node.getAttribute(attr), target = translate(source);
          if (source !== target) node.setAttribute(attr, target);
        }
        node.childNodes.forEach(localize);
      }
    }
    document.addEventListener("DOMContentLoaded", () => {
      localize(document.documentElement);
      new MutationObserver(records => {
        for (const record of records) {
          if (record.type === "childList") record.addedNodes.forEach(localize);
          else localize(record.target);
        }
      }).observe(document.documentElement, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:attrs});
    });
  }
})();
