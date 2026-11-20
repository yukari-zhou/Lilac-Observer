# 衡见 Hengjian｜A 股行情、财报与 AI 策略复核

衡见是在本机运行的 A 股研究台。选择一个指数或上市公司，可以把报价与收盘走势、公司财报与公告、未来 1／5／20 个交易日的情景区间放在一起看。每条策略给出触发条件、风险复核线和依据。量化计算由 Python 完成，证据复核可选用 Codex、兼容 API 或本机模型。

**衡见**取“权衡证据，形成判断”之意。A local-first research terminal for China's A-share market, with financial filings, walk-forward evaluation and optional model review.

[下载 v0.1.0](https://github.com/yukari-zhou/hengjian/releases/tag/v0.1.0) · [更新记录](CHANGELOG.md) · [研究方法](docs/research.md)

![衡见研究台展示合成走势、情景区间和风险复核线](docs/terminal-preview.png)

*界面示例，使用合成行情。*

## 启动

准备 Python 3.10 或更新版本，下载并解压仓库，或用 Git 克隆后进入项目目录。首次使用需要联网安装依赖并获取行情与证券目录。仓库只分发程序、文档和测试；行情缓存由每台机器分别建立。

| 系统 | 从项目目录启动 |
| --- | --- |
| Windows | 双击 `start.cmd`，或在 PowerShell 中运行 `.\start.cmd` |
| macOS / Linux | 在终端运行 `bash start.sh` |

脚本会准备 `.venv` 并启动本机服务。默认浏览器打开后，选择「市场指数」，查看沪深 300 等六个指数；也可在搜索框输入证券代码或公司简称，例如 `600519`，点击「加入自选」打开股价走势图。自选股会保留到下次启动。[打开本机研究台](http://127.0.0.1:8765/)

新启动的服务需要保留终端窗口，按 `Ctrl+C` 可停止。Windows 重复双击启动脚本时，若提示「研究台已经在运行」，可关闭这次打开的窗口。端口冲突时，在已安装依赖的虚拟环境中运行 `python app.py --open --port 8766`。

## 选择复核模型

打开右上角「模型设置」，选择接入方式，再点击「保存设置」。

| 方式 | 需要填写什么 | 如何确认 |
| --- | --- | --- |
| **仅量化** | 无 | 页面仍可更新行情、计算因子和查看历史验证，适合先熟悉研究方法 |
| **Codex CLI** | 安装并登录 Codex CLI。模型栏可留空，或填写账户有权使用的模型 ID | 在启动服务的终端运行 `codex login status`。复核通过命令行在后台完成，可关闭 Codex 桌面窗口 |
| **兼容 API** | 填写 API 地址、模型 ID、该服务的密钥。本机无鉴权服务可留空密钥 | 服务需支持非流式 `POST /chat/completions`，模型能按提示生成 JSON。界面显示复核状态与结果 |

**云端示例。** 使用 DeepSeek 时，可将 API 地址填为 `https://api.deepseek.com`，模型 ID 使用该账户当前可调用的名称，密钥使用对应服务签发的 API key。其他服务可填写形如 `https://服务域名/v1` 的基址，或完整的 Chat Completions 接口地址。需要适配专有协议的模型，可通过提供该兼容接口的网关接入。[DeepSeek 官方接入示例](https://api-docs.deepseek.com/) · [Codex CLI 安装说明](https://developers.openai.com/codex/cli/)

**本机示例。** 已经运行 Ollama 且已下载模型时，选择「兼容 API」，地址填写 `http://127.0.0.1:11434/v1`，模型 ID 填写 `ollama list` 中的完整名称。远程端点使用 HTTPS，本机回环地址支持 HTTP。[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)

开启云端复核时，服务会把当前标的、报价、量化结果与相关证据摘要提交给所选服务商。用量受自己账户的额度和计费规则约束。本机设置文件中的 API 密钥以明文保存，设置接口仅返回密钥状态。若希望密钥只存在于进程环境，可在启动前配置下表变量。

| 环境变量 | 含义 |
| --- | --- |
| `HENGJIAN_PROVIDER` | `off`、`codex` 或 `api`；首次无显式配置时，有可用 Codex 命令则选 Codex，其余选仅量化 |
| `HENGJIAN_CODEX_MODEL` | 可选的 Codex 模型 ID；兼容旧版 `ASTRA_MODEL` |
| `HENGJIAN_API_BASE_URL`、`HENGJIAN_API_MODEL` | 兼容服务的基址和模型 ID |
| `HENGJIAN_API_KEY` | 启动进程使用的密钥，仅用于与环境配置匹配的 API 基址 |
| `HENGJIAN_RUNTIME_DIR` | 自选股、模型设置及研究留档的存储目录，默认 `.runtime/` |
| `HENGJIAN_CACHE_DIR` | 行情与证券目录缓存根目录，兼容旧版 `ASTRA_CACHE_DIR` |
| `HENGJIAN_OFFLINE=1` | 关闭网络数据采集和 AI 复核，查阅已有缓存，兼容旧版 `ASTRA_OFFLINE=1` |

旧版变量 `ASTRA_ENABLED=0` 仍可强制关闭 AI 复核。页面保存的字段优先于环境初值。相同端点的密钥栏留空可沿用原密钥；更换端点后请为新端点填写其专用密钥。可用「清除已保存密钥」取消密钥。备份、上传或提交文件前，请单独处理运行目录中的模型设置、自选列表与研究记录。

## 从行情读到策略

1. **看时点。** 报价附来源时间。分时图显示最近可用交易日的分钟价格；日线图和期末预测从最近一次完整收盘起算。股票以元／股显示，指数以点显示。
2. **看证据。** 在「因子与情报」核对财报期、公告时间和原文。指数财报来自前 20 大权重成份股，页面显示实际覆盖的指数权重；个股财报直接匹配所选公司。
3. **看基准。** 在「历史验证」先看该周期有多少样本，再比较价格模型与基准的命中率和平均绝对误差。如个股显示「样本待积累」，图上给出的区间仅作波动参考。
4. **看复核。** 量化层计算范围及风险复核线，所选模型核对方向、证据冲突与适用范围。符合条件的实际复核结果会留档，后续再查看同一标的和周期时，按真实收盘核验。[研究方法、指标与局限](docs/research.md)

## 常见问题

| 现象 | 排查方法 |
| --- | --- |
| 浏览器没打开 | 访问启动窗口给出的本机地址。`/api/health` 可检查服务状态。若窗口报告端口冲突，请更换端口 |
| 首次搜索为空，或行情标为「缓存」「来源延迟」 | 检查本机网络能否访问对应数据源，并核对最后更新时间。新安装需要成功联网一次才能离线查阅已取得的标的 |
| 有日线，个股仍显示「数据不足」 | 检查是否已有至少 60 根有效收盘日线，以及日线是否为前复权。分时时点或未收盘日线不会补入样本 |
| Codex 没有完成复核 | 确认启动环境能执行 `codex --version`、`codex login status`，并检查所填模型权限。也可从「模型设置」切换至 API 或仅量化 |
| API 失败或模型输出无效 | 核对端点、模型 ID、密钥与配额。端点需返回 Chat Completions 格式的消息，模型输出须包含可解析的决策与依据。检查后保存设置并刷新研究 |

## 数据与接口

程序按需读取交易所目录、财经资讯、公司公告、指数权重和国家统计局发布。实际传输存在延迟，各来源的可用性、使用范围和再分发条款各有规定。对外分发行情、历史价格或指数权重前，请核对相关来源授权。行情、复核结论及保护位仅供研究，不构成投资建议。[行情产品与许可](https://www.sseinfo.com/services/assortment/level1/) · [国证指数数据服务](https://www.cnindex.com.cn/zh_services/data_licensing/index.html?act_menu=4&act_service=3)

本机 HTTP 接口、返回值单位、数据来源及测试命令见 [开发与研究说明](docs/research.md)。
