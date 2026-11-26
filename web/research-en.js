(() => {
  "use strict";
  const {add, translate: t} = window.LilacI18n;
  const entries = `
历史漂移|Historical drift
均线趋势|Moving-average trend
期限动量|Horizon momentum
量价确认|Price–volume confirmation
下行波动|Downside volatility
已兑现区间收益的收缩截距|Intercept estimated from past returns and shrunk toward zero
成交量缺失，因子贡献为零|Volume unavailable. This factor contributes zero.
20 日收盘价持平|Closing prices were unchanged over 20 sessions.
价格模型|Price model
外部情报|External evidence
行业景气|Industry activity
宏观景气|Economic activity
市场情绪|Market sentiment
新闻与政策|News & policy
等待数据|Await data
暂缓新增风险敞口|Hold off on adding exposure.
暂无止损参考|No stop reference available.
更新日线后复核|Reassess after the next daily bar.
尚无可用检验窗口。|No eligible validation windows yet.
预测周期可选 1、5、20 个交易日|Choose a horizon of 1, 5 or 20 trading sessions.
个股日线的前复权口径尚未确认。当前可查看走势图，待复权序列可用后评估。|The adjustment basis of the daily prices is unconfirmed. The chart is available. The model will run once adjusted prices are available.
个股当前停牌或当日尚无有效成交|The stock is suspended or has no confirmed trades today.
最新日线距评估日超过 7 个自然日|The latest daily bar is over seven calendar days old.
已有更新交易日的报价，日线尚未补齐该交易日收盘数据|A more recent trading day has a quote but no corresponding daily close.
最新报价的昨收与日线末值不符|The previous close in the quote differs from the final daily close.
收盘报价与前复权末根日线价格不一致，等待核对除权或数据更新|The closing quote differs from the latest adjusted close. Await a corporate-action check or a data update.
报价来源未确认当前有效行情|The source has not confirmed a current quote.
等待新日线后再评估|Reassess when new daily data arrive.
等待样本积累|Await more observations
暂缓新增个股敞口|Hold off on increasing exposure to this stock.
防守观察|Defensive watch
暂停新增多头敞口|Hold off on adding long exposure.
等待覆盖成本|Await a return above trading costs
暂缓新增多头敞口|Hold off on adding long exposure.
参考股数下中枢情景的净收益未转正，等待成本后空间改善|For the reference quantity, the central scenario yields no positive net profit. Wait for a larger margin after costs.
等待突破确认|Await breakout confirmation
收盘确认后分批建立研究仓位|Build the research position in stages after a confirmed close.
观察偏强信号|Monitor bullish signals
保持观察仓位，暂缓加仓|Maintain a monitoring position and defer additions.
方向与误差检验尚未同时超过基准，等待下一收盘复核|Direction accuracy and forecast error have yet to beat both benchmarks. Reassess at the next close.
区间观察|Monitor the range
暂缓追涨，保留可用资金|Keep cash available and avoid chasing a rise.
除权除息后按同口径重算保护价。停牌、跌停或跳空时，实际成交价可能偏离保护价。|Recalculate the protective level on the same price basis after corporate actions. A halt, limit-down move or gap can prevent execution at that level.
指数点位需换算为跟踪产品价格，跳空会扩大损失。|Convert index points to the price of the tracking instrument. Price gaps can increase losses.
未取得时点、范围及方向均可用的外部证据，本次采用价格模型。|No external evidence met the timing, relevance and direction criteria. This estimate uses the price model.
尚无纳入本次估计的财报或估值证据。|This estimate includes no eligible financial statements or valuation evidence.
已兑现的误差不足 12 个，区间暂用 20 日波动率的 1.28 倍估算。|Fewer than 12 forecast errors have matured. The range uses 1.28 times 20-session volatility.
个股走势、验证收益与保护线使用前复权日线。发生分红送转后，历史价格基准会更新。|The chart, validation returns and protective levels use adjusted daily prices. Dividends and share distributions can change the historical price basis.
本周期尚无可用样本外记录，中枢沿用收盘价，上下沿仅作波动参考。|No out-of-sample forecasts have matured for this horizon. The midpoint is the closing price and the bounds illustrate volatility.
当前检验尚未同时满足至少 24 个样本、方向命中率和平均绝对误差超过各自基准。|Validation requires at least 24 observations, higher direction accuracy and lower mean absolute error than the benchmarks. These criteria are not yet all met.
逐期滚动岭回归 · 误差分位数校准|Walk-forward ridge regression · Forecast-error quantile calibration
未取得本公司可用财报，已跳过财报因子|No eligible issuer financials available. The financial factor was omitted.
未取得成份股财报，已跳过财报因子|No constituent financials available. The financial factor was omitted.
原始日线（复权口径未确认）|Raw daily prices (adjustment basis unconfirmed)
当前日线的复权口径未确认，跨除权除息日涨跌可能失真。|The adjustment basis is unconfirmed. Returns across ex-dividend or ex-rights dates may be distorted.
当前在市证券目录未收录该标的，已停止获取现价，仅显示本机已有历史。|This stock is absent from the current listings. Only locally saved history is available.
最新报价与最近收盘日属于不同时点。|The latest quote and most recent daily close have different timestamps.
最新报价与已完成日线基准日不同，模型以最近收盘日校准。|The latest quote and completed daily bar are on different dates. The model is calibrated to the latest daily close.
股价|Share price
市场新闻|Market news
宏观数据|Economic data
使用最近一次成功采集的缓存。|Using the last successful fetch.
使用随附历史快照。|Using the bundled historical snapshot.
数据暂缺。|Data temporarily unavailable.
报价时间滞后。|The quote is delayed.
来源未显示当日成交。|The source shows no trades today.
本次使用上次成功采集的本地缓存。|Using the last successful local fetch.
本次使用随附历史快照。|Using the bundled historical snapshot.
来源时标落后，实时性未确认。|The timestamp is delayed. Live status is unconfirmed.
沪市主板|Shanghai main board
深市主板|Shenzhen main board
创业板|ChiNext
科创板|STAR Market
北交所|Beijing Stock Exchange
等待有效数据|Waiting for valid data
等待有效行情后再复核模拟持仓|Waiting for valid market data before reviewing the paper position.
收盘样本不足，等待日线数据|Too few closes for a review. Awaiting daily data.
本机已关闭 AI 复核|AI review is turned off locally.
等待模型复核|Waiting for model review.
等待行情分析|Waiting for market analysis.
模型正在研判当前证据|The model is reviewing the available evidence.
等待确认，暂停新增风险敞口|Wait for confirmation before increasing exposure.
控制已有风险敞口，暂停加仓并复核保护位|Limit current exposure, pause additions and reassess the protective level.
仅供历史复盘，等待有效行情|Historical review only. Await a valid current quote.
当前模拟账户未持有该股，观察入场条件|The paper account holds no shares in this stock. Monitor the entry conditions.
当前持仓暂无可卖股数，等待解除 T+1 限制后复核|No shares are sellable. Reassess once the T+1 restriction lifts.
模型已完成证据复核|The model has finished reviewing the evidence.
模型超时或响应格式无效，稍后自动重试|The model timed out or returned an invalid response. A retry is scheduled.
不支持的界面语言|Unsupported interface language.
模拟仓位与标的不匹配|The paper position does not match the selected stock.
未检测到 Codex CLI。安装后运行 codex login。|Codex CLI was not found. Install it and run codex login.
Codex 登录已失效，请运行 codex login。|Your Codex sign-in expired. Run codex login.
Codex 调用额度暂不可用，稍后自动重试。|Codex quota is temporarily unavailable. A retry is scheduled.
Codex 调用未完成，请检查本机 CLI 版本、模型权限和网络。|Codex did not finish. Check the CLI version, model access and network connection.
模型 API 请求受限或额度不足（HTTP 429），稍后自动重试。|Model API rate or quota limit reached (HTTP 429). A retry is scheduled.
模型 API 连接失败或超时，请检查网络和服务地址。|The model API connection failed or timed out. Check the network and endpoint.
Codex CLI 默认模型|Codex CLI default model
本机模型设置无法读取，请重新保存设置。|The local model settings could not be read. Save them again.
本机模型配置无效，请检查环境变量或重新保存设置。|The local model configuration is invalid. Check environment variables or save the settings again.
模型配置格式无效|Invalid model configuration.
请选择 Codex、兼容 API 或关闭复核|Choose Codex, a compatible API or quantitative-only mode.
请输入有效的 Codex 模型 ID，或留空使用 CLI 默认模型|Enter a valid Codex model ID or leave it blank to use the CLI default.
请输入服务商提供的模型 ID|Enter a model ID from your provider.
请选择模型接入方式|Select a model connection.
模型配置包含未知字段|The model configuration contains unrecognized fields.
清除密钥选项无效|Invalid option for clearing the key.
请选择更新密钥或清除密钥|Choose either updating or clearing the API key.
API 密钥格式无效|Invalid API key format.
API 地址格式无效|Invalid API endpoint format.
API 模型名格式无效|Invalid API model name.
Codex 模型名格式无效|Invalid Codex model name.
API 地址须为不含凭据、查询参数和片段的服务地址|Enter the endpoint without credentials, query parameters or URL fragments.
远程 API 请使用 HTTPS，本机回环地址可用 HTTP|Remote endpoints require HTTPS. Local loopback endpoints may use HTTP.
缺少该股票的有效报价|No valid quote for this stock.
报价须包含有效的原始股价、来源和交易所时点|The quote must include a valid unadjusted price, source and exchange timestamp.
模拟交易仅支持自选 A 股股票|Paper trading is available for watchlisted A-share stocks.
请选择买入或卖出，并填写正整数股数|Choose buy or sell and enter a positive whole number of shares.
模拟订单标识无效|Invalid paper order ID.
该订单标识已用于另一笔模拟交易，请重新预览|This ID belongs to a different paper order. Preview again.
当前报价不可用于模拟成交|This quote is ineligible for a paper fill.
模拟可用现金不足以支付本笔交易及费用|Available paper cash is insufficient to cover the order and fees.
尚无可用报价|No quote available.
该股停牌或尚无有效成交|The stock is suspended or has no confirmed trades.
连续竞价时段以外，仅可测算费用|Outside continuous trading hours. Cost previews are available.
连续竞价时段以外，可预览费用和持仓变化|Outside continuous trading hours. You can preview costs and changes to your holdings.
报价时间无效，请刷新|Invalid quote timestamp. Refresh the quote.
需要同一交易时段内的实时有效报价|A live quote from the current trading session is required.
暂无可成交的对手方报价|No executable quote on the opposite side of the book.
滑点后的成交价超出当日报价限制|The fill price after slippage exceeds the daily price limits.
请选择自选股中的上市公司|Select a company on your watchlist.
请先将该股票加入自选|Add this stock to the watchlist first.
无效的模拟订单|Invalid paper order.
模拟订单字段不完整或含未知字段|The paper order has missing or unrecognized fields.
请选择买卖方向并输入正整数股数|Select a side and enter a positive whole number of shares.
无效的订单编号|Invalid order ID.
请先预览当前报价|Preview the current quote first.
报价已变化，请重新预览并确认|The quote changed. Preview and confirm again.
金额必须为有效数值|Enter a valid monetary amount.
金额必须为非负有限数值|Enter a finite, nonnegative amount.
股数必须为正整数|Enter a positive whole number of shares.
请选择买入或卖出|Choose buy or sell.
报价至少为 0.01 元|The minimum quote is CNY 0.01.
当前数据处理失败，请稍后刷新。详情见本机服务日志。|Data processing failed. Refresh shortly and check the local service log for details.
请提交有效的 JSON 设置|Submit a valid JSON configuration.
请提交有效的股票代码和自选操作|Submit a valid stock ticker and watchlist action.
未在 A 股上市证券目录中找到该股票|Stock not found in the A-share directory.
该股票仍有模拟持仓，请平仓后再移出自选|Close the paper position before removing this stock from the watchlist.
无效的持仓复核参数|Invalid position review parameters.
资源不存在|Resource not found.
仅允许本机访问|Local access only.
请从本机研究台访问|Open this page from the local terminal.
设置只能从本机研究台更改|Change these settings from the local research terminal.
搜索词过长|Search query is too long.
证券名录暂不可用。首次使用请联网，稍后重试。|The securities directory is unavailable. Connect to the network on first use and retry shortly.
请选择有效指数或先将股票加入自选，周期可选 1、5、20 日|Choose a valid index or watchlist the stock first. Supported horizons are 1, 5 and 20 sessions.
该股票已移出自选|This stock was removed from the watchlist.
股票代码无效|Invalid stock ticker.
未知指数|Unknown index.
未找到该上市公司|The listed company was not found.
数据与方法说明|Data and methodology notes
预测方法与验证边界|Forecast assumptions and validation scope
价格模型区间|Price-model range
营收|Revenue
上市公司定期报告|Issuer periodic filings
国证指数 / 东方财富|CNI / Eastmoney
中证指数 / 东方财富|CSI / Eastmoney
按匹配行业的指数权重汇总产出同比，作为弱景气信号。产出增速与盈利和市场预期可能不同。|Year-over-year industrial output is weighted by the index exposure to matched sectors. This is a weak activity signal. Output growth can differ from earnings growth and market expectations.
相对50的偏离与环比分别占70%、30%，除以3后限幅；无环比时只用偏离。|The signal weights deviation from 50 at 70% and the monthly change at 30%, then scales by one third and caps the result. If monthly change is missing, only the deviation is used.
A 股市场快讯。正文可查看行业表现与盘面细节。|A-share market update. The original report covers sector performance and trading details.
全市场同向个股达到3500家时，按报道家数÷5500限幅计分。|When at least 3,500 stocks move in the same direction, the score uses the reported count divided by 5,500, capped at one.
公司上市公告书披露行业为 C34 通用设备制造业|The company’s listing notice classifies it under C34, general-purpose machinery manufacturing
自动化设备|Automation equipment
银行Ⅱ|Banking
银行|Banking
股份制银行|Joint-stock banks
国有大型银行|Large state-owned banks
城商行|City commercial banks
保险Ⅱ|Insurance
证券Ⅱ|Securities
化学制药|Pharmaceuticals
有色金属|Nonferrous metals
贵金属|Precious metals
工业金属|Industrial metals
乘用车|Passenger vehicles
商用车|Commercial vehicles
汽车零部件|Auto components
半导体|Semiconductors
通信设备|Communications equipment
消费电子|Consumer electronics
计算机设备|Computer equipment
元件|Electronic components
光学光电子|Optics and optoelectronics
专用设备|Special-purpose machinery
通用设备|General-purpose machinery
电池|Batteries
白色家电|Major appliances
电力|Electric power
白酒Ⅱ|Baijiu spirits
饮料乳品|Beverages and dairy
其他|Other
汽车制造业|Motor vehicle manufacturing
计算机、通信和其他电子设备制造业|Computer, communications and electronic equipment manufacturing
专用设备制造业|Special-purpose machinery manufacturing
通用设备制造业|General-purpose machinery manufacturing
电气机械和器材制造业|Electrical machinery and equipment manufacturing
铁路、船舶、航空航天和其他运输设备制造业|Rail, shipbuilding, aerospace and other transport equipment manufacturing
化学原料和化学制品制造业|Chemical materials and products
医药制造业|Pharmaceutical manufacturing
纺织业|Textile manufacturing
非金属矿物制品业|Non-metallic mineral products
黑色金属冶炼和压延加工业|Ferrous metal smelting and rolling
有色金属冶炼和压延加工业|Nonferrous metal smelting and rolling
电力、热力生产和供应业|Electricity and heat supply
农副食品加工业|Agricultural food processing
酒、饮料和精制茶制造业|Alcohol, beverages and refined tea manufacturing
`.trim().split("\n").map(line => line.split("|"));

  // Keep counts, signs, currency and horizon from each exact model template.
  const rules = [
    [/^20 日均线 ([\d,.]+)，60 日均线 ([\d,.]+)$/, "20-session moving average $1, 60-session moving average $2"],
    [/^过去 (\d+) 个交易日涨跌 ([+−-]?[\d.]+%)$/, "Return over the past $1 sessions: $2"],
    [/^10 日成交量加权涨跌强度 ([+−-]?[\d.]+)$/, "10-session volume-weighted price pressure: $1"],
    [/^20 日负收益平方和占比 ([\d.]+%)$/, "Downside share of squared returns over 20 sessions: $1"],
    [/^(\d+) 条有方向证据，(\d+) 个来源，按披露时效、适用范围和置信度折减$/, "$1 directional observations from $2 sources, discounted for age, relevance and confidence."],
    [/^当前有 (\d+) 根有效日线，模型至少需要 60 根。$/, "$1 valid daily bars available. The model requires at least 60."],
    [/^数据截止 ([\d-]+)，历史情景不可直接作为当前入场依据$/, "Data through $1. The historical scenario provides no current entry signal."],
    [/^(\d+) 日周期尚无成熟的样本外验证窗口，待更多交易日收盘后复核$/, "No out-of-sample window has matured for the $1-session horizon. Reassess after more daily closes."],
    [/^收盘跌破 ([\d,.]+) (元|点)时，复核已有多头敞口并降低风险$/, (_, level, unit) => "If the close falls below " + level + " " + t(unit) + ", review existing longs and reduce risk."],
    [/^收盘突破近 (\d+) 日高点 ([\d,.]+) (元|点)后，再按可承受损失确定份额(。用届时股价及实际股数重算，预期空间需覆盖买卖滑点和税费)?$/,
      (_, sessions, level, unit, costs) => "After a close above the " + sessions + "-session high of " + level + " " + t(unit) + ", size the position according to the loss you can tolerate."
        + (costs ? " Recalculate for the prevailing price and share count. Expected gains must cover slippage, fees and tax on the round trip." : "")],
    [/^观察能否收盘突破 ([\d,.]+) (元|点)，并在新日线到达后重新计算$/, (_, level, unit) => "Watch for a close above " + level + " " + t(unit) + ". Recalculate when the next daily bar arrives."],
    [/^现有多头按参考收盘价下方 ([\d,.]+) (元|点)设置复核线，以同一价格口径下入场时确定的保护线为下限，收盘触及后按可成交价格减仓。(.+)$/,
      (_, distance, unit, tail) => "For existing longs, set the review level " + distance + " " + t(unit) + " below the reference close. Keep the original protective level as a floor on the same price basis. If the closing price reaches the threshold, reduce exposure at an executable price. " + t(tail)],
    [/^每次收盘复核，最迟在第 (\d+) 个交易日收盘重新评估$/, "Review at each close and reassess by the close of session $1."],
    [/^预测从 ([\d-]+) 收盘 ([\d,.]+) (元|点)起算，区间为第 (\d+) 个交易日的收盘情景。$/,
      (_, day, price, unit, horizon) => "From the " + day + " close of " + price + " " + t(unit) + ", the range describes the closing price after " + horizon + " trading sessions."],
    [/^情报截止 ([\d-]+ [\d:]+)（上海），共 (\d+) 个方向性类别参与。$/, "Evidence as of $1 Shanghai time. Directional evidence from $2 categories contributes to this estimate."],
    [/^(.+)，展示历史复盘。$/, (_, reason) => t(reason) + " Showing a historical review."],
    [/^每次仅使用当时已收盘的数据，训练满 12 个已兑现区间后开始检验，同期限窗口互不重叠。方向按价格模型中枢涨跌的正负判定，方向基准为始终看涨，绝对收益误差基准为(点位持平|股价持平)。覆盖率检验目标 80% 的价格模型区间。当前情报修正、成交成本和止损执行未纳入检验。(个股检验使用本次取得的前复权序列，分红送转后历史基准可能与当时留档的价格不同。)?$/,
      (_, baseline, stock) => "Validation uses only closes available at each forecast date. Testing begins after 12 training outcomes and uses non-overlapping windows for each horizon. Direction is the sign of the change to the forecast midpoint. Benchmarks are always-up for direction and an unchanged " + (baseline === "股价持平" ? "share price" : "index level") + " for absolute return error. The price-model interval targets 80% coverage. Current evidence adjustments, trading costs and stop execution are excluded."
        + (stock ? " Stock tests use the current adjusted price series. Past prices can differ from the archived observations after dividends or share distributions." : "")],
    [/^该板块单笔模拟市价成交上限为 (\d+) 股$/, "The maximum paper market order on this board is $1 shares."],
    [/^当前仅有 (\d+) 股可卖；当日买入的股票须待下个交易日$/, "Only $1 shares can be sold. Shares bought today become eligible on the next trading day."],
    [/^该板块每笔至少 (\d+) 股，按 (\d+) 股递增；不足起点的余股可一次卖清$/, "Orders on this board start at $1 shares in increments of $2. A smaller remaining balance may be sold in full."],
    [/^模型 API 返回 HTTP (\d+)，请检查密钥和模型权限。$/, "The model API returned HTTP $1. Check the key and model access."],
    [/^模型 API 返回 HTTP (\d+)，请检查服务地址、模型 ID 和兼容协议。$/, "The model API returned HTTP $1. Check the endpoint, model ID and protocol compatibility."],
    [/^(报价|日线|股价|市场新闻|宏观数据)：(.+。)$/, (_, field, reason) => t(field) + ": " + t(reason)],
    [/^权重股财报 · (\d+) 家，覆盖指数 ([\d.]+%)$/, "Constituent financials · $1 firms covering $2 of the index"],
    [/^按 ([\d-]+) 权重，从前 20 大样本匹配已披露财报。行业覆盖（占指数权重）：(.+)。样本内营收同比与归母净利润同比按 4:6 合成，覆盖率用于降低局部样本的影响。$/,
      (_, stamp, sectors) => "Disclosed financials were matched to the 20 largest constituents by weight on " + stamp + ". Sectors covered as a share of the index: " + sectors.split("、").map(t).join(", ") + ". Revenue and attributable profit growth are combined at weights of 40% and 60%. The coverage adjustment reduces the impact of a partial sample."],
    [/^([^ ·]+) ([\d.]+%)$/, (_, sector, weight) => t(sector) + " " + weight],
    [/^(.+) · 截至 ([\d-]+) 的累计业绩$/, "$1 · Year-to-date results through $2"],
    [/^年初至报告期末，(.+)。披露日 ([\d-]+)。(?: 数据商行业分类为(.+)。)?$/,
      (_, metrics, published, sector) => "Year to date: " + metrics.split("，").map(t).join(", ") + ". Disclosed on " + published + "." + (sector ? " Provider sector: " + t(sector) + "." : "")],
    [/^(营收|归母净利润)(?: ([,\d.-]+) 亿元)?(?:（同比 ([+\d.-]+%)）)?$/,
      (_, name, amount, growth) => (name === "营收" ? "Revenue" : "Profit attributable to shareholders") + (amount ? " " + amount + " × 100m CNY" : "") + (growth ? " (" + growth + " YoY)" : "")],
    [/^(.+)景气 · (.+)$/, (_, sector, headline) => t(sector) + " activity · " + headline],
    [/^财报数据行业分类为([^。]+)$/, (_, sector) => "The financial data provider classifies the company under " + t(sector)],
    [/^(.+)。本次发布中，(.+)工业增加值同比 ([+\d.-]+%)。该指标衡量行业产出，个股订单与盈利还取决于产品结构、价格和成本。$/,
      (_, classification, sector, growth) => t(classification) + ". This release reports " + growth + " YoY value-added growth for " + t(sector) + ". It measures industry output. Company orders and earnings also depend on product mix, pricing and costs."],
    [/^(.+。) 与权重股样本直接匹配的行业占指数 ([\d.]+%)。$/,
      (_, note, weight) => t(note) + " Sectors matched directly to the constituent sample represent " + weight + " of the index."],
    [/^分行业工业增加值同比：(.+)。$/, (_, sectors) => "Industrial value-added growth YoY: " + sectors.split("，").map(item =>
      item.replace(/^(.+)([+-][\d.]+%)$/, (_, sector, growth) => t(sector) + " " + growth)).join(", ") + "."],
    [/^制造业 PMI ([\d.]+%)，荣枯线 50%。(?:环比([+-][\d.]+)个百分点。)?$/,
      (_, pmi, change) => "Manufacturing PMI: " + pmi + ". The expansion threshold is 50%." + (change ? " Change from the previous month: " + change + " percentage points." : "")],
    [/^快讯报道的市场广度：(.+)。家数来自新闻文本。$/, "Market breadth according to the original report: “$1”. Counts are taken from the source text."],
    [/^公告类别：(.*)$/, "Filing category: $1"],
  ];
  add(entries, rules);
})();
