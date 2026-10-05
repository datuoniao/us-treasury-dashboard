# 美国国债数据看板 (US Treasury Dashboard)

一个**单文件、可离线**的交互式美国国债数据看板，聚焦三大模块：

| 模块 | 内容 |
|---|---|
| **规模与结构** | 联邦政府总债务（Debt to the Penny）、公众持有 vs 政府内部持有、按证券类型的债务结构（MSPD） |
| **收益率与曲线** | 名义收益率曲线（1M–30Y）、关键期限走势、10Y−2Y / 10Y−3M 利差、TIPS 实际收益率与盈亏平衡通胀预期 |
| **海外持仓 (TIC)** | 各国/地区持有美债规模、主要持有国排名与份额、头部持有国时序演变 |

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

## 频率口径说明

- **日频数据一律重采样为周频**，统一取**周五**为周度节点：利率类取当周均值，存量类取当周末值。
- **月频数据（债务结构、TIC）保持月频**，不做上采样。
- 因此看板中**不存在日频刻度**，避免高频噪声干扰中期趋势观察。

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
- **Python 依赖**：仅使用标准库（`csv`/`io`/`json`/`re`/`datetime`），无需额外安装第三方包。
- **本地 git 推送**：若所在环境存在证书吊销检查问题（schannel `CRYPT_E_NO_REVOCATION_CHECK`），可为该仓库单独设置 `git config http.sslVerify false` 规避。

## 许可

数据来源于美国财政部公开数据，仅供研究与学习使用。
