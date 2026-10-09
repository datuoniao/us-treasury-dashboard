# 美国国债数据看板 (US Treasury Dashboard)

一个**单文件、可离线**的交互式美国国债数据看板，聚焦三大模块：

| 模块 | 内容 |
|---|---|
| **规模与结构** | 联邦政府总债务（Debt to the Penny）、公众持有 vs 政府内部持有、按证券类型的债务结构（MSPD） |
| **收益率与曲线** | 名义收益率曲线（1M–30Y）、关键期限走势、10Y−2Y / 10Y−3M 利差、TIPS 实际收益率与盈亏平衡通胀预期 |
| **海外持仓 (TIC)** | 各国/地区持有美债规模、主要持有国排名与份额、头部持有国时序演变 |
| **日本专题（2018 至今）** | 日本持仓 × 美元/日元汇率 × 美日10年利差 三轴对比 |

## 在线预览

**https://datuoniao.github.io/us-treasury-dashboard/**

由 GitHub Actions 自动部署（`.github/workflows/pages.yml`）：每次推送到 `main` 会把 `output/us_treasury_dashboard.html` 作为站点首页发布，**不改变原目录结构**。

也可下载 `output/us_treasury_dashboard.html` 后**双击打开**（HTML 内已内联 ECharts 与全部数据，无需联网、无需服务器）。

## 数据来源

| 数据 | 来源 | 频率（源） | 看板频率 |
|---|---|---|---|
| 名义 / TIPS 实际收益率曲线 | 美国财政部 Daily Treasury Rates (`home.treasury.gov`) | 日 | **周（周五）** |
| 联邦政府总债务 | Treasury Fiscal Data API — *Debt to the Penny* | 日 | **周（周五）** |
| 债务结构 | Treasury Fiscal Data API — *MSPD Table 1* | 月 | 月 |
| 各国持有美债 | 美国财政部 TIC — `mfhhis01.txt`（历史）/ `slt_table5.txt`（最新） | 月 | 月 |
| 美元/日元汇率 | FRED — `DEXJPUS` | 日 | **周（周五）** |
| 日本10年国债收益率 | 日本财务省 — 国債金利情報 `jgbcm_all.csv` / `jgbcm.csv` | 日 | **周（周五）** |
| 美日10年利差 | 自行计算（美债10年 − 日本10年，同日对齐后相减） | — | **周（周五）** |

> 日本专题图固定显示 **2018 年至今**，不随时间范围切换：持仓为月频，汇率与利差为周频。

## 频率口径说明

- **日频数据一律重采样为周频**，统一取**周五**为周度节点：利率类取当周均值，存量类取当周末值。
- **月频数据（债务结构、TIC）保持月频**，不做上采样。
- 因此看板中**不存在日频刻度**，避免高频噪声干扰中期趋势观察。

## 口径说明（易混淆项）

- **外资持债占比的分母**用「联邦债务总额」（Debt to the Penny 的 `tot_pub_debt_out_amt`），
  而非仅剔除政府内部持有的「公众持有债务」。原因：TIC 统计的是**全部**海外持仓，
  与联邦总债务口径对应；若用公众持有作分母，占比会被系统性高估（如 2015-06 会由 33.9% 虚高至 47.1%）。
- **债务结构旭日图**的外环含「其他 Other」类别，收纳 Federal Financing Bank 等未单列的
  可流通项，使父环（可流通总额）与子项之和严格一致。
- TIC 只按托管地统计，并非持有人真实国籍；中国大陆持仓不含中国香港、中国台湾（单列显示）。

## 目录结构

```
us-treasury-dashboard/
├── fetch_data.sh           # 抓取原始数据到 data_raw/（bash + curl）
├── build_dashboard.py      # 解析、重采样、组装并渲染单文件 HTML（纯本地，不联网）
├── template.html           # 页面骨架 + CSS 主题 + 11 个图表配置与渲染逻辑
├── vendor/
│   └── echarts.min.js      # 构建期内联的 ECharts 源
├── data_raw/               # 原始数据底表（收益率 CSV、Fiscal Data JSON、TIC txt）
├── cache_data.json         # 中间解析缓存
└── output/
    └── us_treasury_dashboard.html   # 最终交付物（单文件自包含）
```

## 复现步骤

```bash
# 1. 抓取原始数据（需联网）
bash fetch_data.sh

# 2. 生成看板（纯本地处理）
python build_dashboard.py
# 产物：output/us_treasury_dashboard.html
```

## 环境注记

- **抓取必须由 shell 直接调用 `curl`**：本项目采用「shell 抓取 + Python 本地解析」的两段式架构。在受限网络环境下，Python 的 `urllib` / `subprocess` 发起的网络请求会被拒绝，而 shell 直接调 `curl` 可稳定通过。
- **FRED 抓取两个坑**（见 `fetch_data.sh`）：① `fred.stlouisfed.org` 的 CA 吊销检查不可达，不加 `-k` 会 TLS 失败返回 `000`；② 发送浏览器 User-Agent 会被对端**重置连接**（curl rc=56），故用 `dl_noua` 不发送自定义 UA。
- **日本财务省 CSV 为 Shift-JIS 编码**，日期是日本年号（`H30.1.4`＝2018-01-04，`R1.5.1`＝2019-05-01），需专用解析（`jp_era_to_iso`），不能用按 UTF-8 读取的通用加载器。
- **Python 依赖**：仅使用标准库（`csv`/`io`/`json`/`re`/`datetime`），无需额外安装第三方包。
- **本地 git 推送**：若所在环境存在证书吊销检查问题（schannel `CRYPT_E_NO_REVOCATION_CHECK`），可为该仓库单独设置 `git config http.sslVerify false` 规避。

## 许可

数据来源于美国财政部公开数据，仅供研究与学习使用。
