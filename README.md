# holdings — Peter 公开组合「跟庄监控器」

> 自动盯一个叫 **Peter** 的人公开晒的实盘组合（`https://petermoportfolio.com/`），
> 每天抓数据、用行情剥离「市场波动」算出他**真正买卖了什么**，做成**网页动态看板**。

---

## 一句话定位

个人量化监控脚本：每天定时爬取某博主公开持仓页，和昨天对比，区分「股价涨跌造成的被动漂移」与「博主主动加减仓」，把结论做成可交互的可视化网页（GitHub Pages 托管）。

核心卖点不是「爬数据」，而是 **「真实调仓 X 光机」算法**——用 yfinance 真实行情把「他在交易」和「只是大盘在动」拆开。

---

## 网页看板（三个视图）

部署在 GitHub Pages（`main` 分支 `/docs`），纯静态，每天数据自动更新后刷新即可：

1. **仓位时间线**（堆叠面积）：每日各标的仓位占比，Top 12 单列，其余归入「其他」。
2. **调仓事件流**（散点）：每次主动调仓一个点，纵轴是剥离涨跌后的真实仓位变动(%)，红=买/建仓、绿=卖/清仓。
3. **净值曲线**（多线）：各标的自最早可得日起按首日收盘价归一化为 100，跨市场（港股/美股/A股）对比涨跌。

---

## 目录结构

```
holdings/
├── .github/workflows/daily.yml   # 每天北京时间 08:00 自动跑 (UTC 00:00)
├── scripts/
│   ├── scraper.py                # 主程序：抓取 + 算调仓 + 生成衍生数据
│   ├── get_detail.py             # 调试用：点开 memos 第一篇，存源码
│   └── diagnose.py               # 调试用：存 memos 页完整源码
├── data/
│   ├── holdings_history.json     # ★核心资产：每天一条持仓快照 {日期: [{code,name,share}]}
│   ├── events.json               # 衍生：历史主动调仓事件列表（X光剥离波动后）
│   ├── price_history.json        # 衍生：各标的 yfinance 历史日线 {code:{date:close}}
│   ├── holdings/                 # latest_holdings.xlsx / holdings_首日.xlsx
│   └── memos/                    # 从网站 memos 页抓的 .docx 笔记
├── docs/
│   ├── index.html                # 看板页面（引入 ECharts）
│   └── app.js                    # 三视图渲染逻辑（fetch data/*.json）
└── requirements.txt
```

---

## 它是怎么工作的

1. **触发**：GitHub Actions `daily.yml` 每天 `cron: '0 0 * * *'`（北京时间早 8 点）自动运行，也支持 `workflow_dispatch` 手动点按钮立刻跑。
2. **抓取**：`scraper.py` 用 **Playwright** 无头 Chromium 打开 `petermoportfolio.com/`，解析「持仓明细表（HoldingsTable）」拿到每只标的的 `code / name / 仓位%`。
3. **算调仓**：和 `data/holdings_history.json` 里昨天的快照对比，核心数学：
   - 组合总收益 `R_p = Σ(旧权重 × 个股涨跌幅)`（涨跌幅来自 `yfinance`）
   - 预期仓位 `= 旧仓位 ×(1+个股涨)/(1+组合涨)`
   - **主动调仓 = 实际仓位 − 预期仓位** → 正的是真加仓、负的是真减仓
   - 分类：`new / buy / sell / sold / drift`（纯被动漂移）
4. **衍生数据**：`generate_events()` 遍历所有相邻日期产出调仓事件（有行情用 X光、无行情降级为仓位差分）；`generate_price_history()` 用 yfinance 拉全部标的的历史日线（增量更新）。
5. **落盘 + 展示**：写入 `holdings_history.json` / `events.json` / `price_history.json`，看板页面 `docs/` 通过 fetch 这些 JSON 动态渲染三视图。

---

## ⚠️ 踩过的坑

### 坑 1：站点改版后持仓抓取串味（2026-07-15 ~ 2026-08-15，已修）

源网站新增「交易信号面板（TradingDesk）」，与「持仓明细表（HoldingsTable）」复用同一个 CSS class `text-xs.text-muted-foreground`，旧选择器把 TradingDesk 的「距止损 X%」当股票代码抓进来，导致 2026-07-15 ~ 2026-08-15 整段脏数据（每天只剩 1-5 条「距止损」串味记录）。

**修复**（`get_holdings()`）：
- 等 tRPC 异步数据加载完再抓（`wait_for_function` + 缓冲）；
- 用 `_looks_like_code()` 严格过滤「止损/已触发/接近/信号」等干扰文字，只留真代码；
- 按 `code` 去重。

**脏数据已清理**：`holdings_history.json` 中 2026-07-15 ~ 2026-08-15 共 29 天已删除，只保留真实持仓日（2026-02-07 ~ 2026-07-14 与 2026-08-16）。

### 坑 2：港股代码格式导致行情全失败（X光失效，已修）

`format_ticker_for_yf()` 原来只处理「带 `.HK` 后缀」和「6位A股」，对持仓历史里**无后缀的5位港股代码**（如 `00700`）直接原样返回 → yfinance 拿不到行情 → `get_daily_return` 全返回 0 → 调仓 X光完全失效（所有漂移/主动调仓算成 0）。

**修复**：5位纯数字按港股处理 → 去前导零补 4 位 + `.HK`（如 `00700`→`0700.HK`）；6位 → A股（`.SS`/`.SZ`）；纯字母 → 美股原样。

> 如果 `holdings_history.json` 又出现奇怪中文 `code`，第一反应是源网站改版，去 `petermoportfolio.com/` 看结构，回到 `get_holdings()` 更新选择器。

---

## 本地运行 / 验证

```bash
pip install pandas openpyxl playwright python-docx yfinance
playwright install chromium

# 跑抓取+分析+生成衍生数据（不推送任何 IM）
python scripts/scraper.py
```

手动触发一次 GitHub Actions 验证线上效果：仓库 → Actions → **Daily Portfolio Tracker** → Run workflow。

---

## 部署（GitHub Pages）

- 源：`main` 分支 `/docs` 目录
- 看板是纯静态页面，`data/*.json` 由 daily.yml 每日更新，Pages 自动反映最新数据。
- 本地预览：`cd docs && python -m http.server 8000`，浏览器开 `http://localhost:8000/`（别用 `file://` 直接打开，fetch 会被 CORS 拦）。

---

## 数据资产说明

- `data/holdings_history.json`：从 2026-02-07 起每天一条，是整套系统最有价值的沉淀，别手滑删了。
- `code` 存的是**无后缀纯数字**（港股 `00700`、A股 `600036`），`format_ticker_for_yf()` 查 yfinance 时再补 `.HK`/`.SS`/`.SZ`。
- `events.json` / `price_history.json`：由脚本自动生成维护，可删（下次运行会重建）。
