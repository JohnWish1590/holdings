# holdings — Peter 公开组合「跟庄监控器」

> 自动盯一个叫 **Peter** 的人公开晒的实盘组合（`https://petermoportfolio.com/`），
> 每天抓数据、用行情剥离「市场波动」算出他**真正买卖了什么**，再推到你 Telegram。

---

## 一句话定位

这是一个**个人量化监控脚本**：每天定时爬取某博主的公开持仓页面，
和昨天对比，区分「股价涨跌造成的被动漂移」与「博主主动加减仓」，
把结论生成可视化面板 + Telegram 告警。

核心卖点不是「爬数据」，而是 **「真实调仓 X 光机」算法**——
光看仓位占比变化分不清「他在交易」还是「只是大盘在动」，
本仓库用 yfinance 真实行情把两者拆开。

---

## 目录结构

```
holdings/
├── .github/workflows/daily.yml   # 每天北京时间 08:00 自动跑 (UTC 00:00)
├── scripts/
│   ├── scraper.py                # 主程序：抓取 + 算调仓 + 生成面板 + 推送
│   ├── get_detail.py             # 调试用：有头浏览器点开 memos 第一篇，存源码
│   └── diagnose.py               # 调试用：有头浏览器存 memos 页完整源码
├── data/
│   ├── holdings_history.json     # ★核心资产：每天一条持仓快照 {日期: [{code,name,share}]}
│   ├── holdings/                 # latest_holdings.xlsx / holdings_首日.xlsx
│   └── memos/                    # 从网站 memos 页抓的 .docx 笔记
├── docs/
│   └── index.html                # 可视化面板：红=主动买、绿=主动卖的柱状图
└── requirements.txt
```

---

## 它是怎么工作的

1. **触发**：GitHub Actions `daily.yml` 每天 `cron: '0 0 * * *'`（北京时间早 8 点）自动运行，
   也支持 `workflow_dispatch` 手动点按钮立刻跑。
2. **抓取**：`scraper.py` 用 **Playwright** 无头 Chromium 打开 `petermoportfolio.com/`，
   解析「持仓明细表（HoldingsTable）」拿到每只标的的 `code / name / 仓位%`。
3. **算调仓**：和 `data/holdings_history.json` 里昨天的快照对比，核心数学：
   - 组合总收益 `R_p = Σ(旧权重 × 个股涨跌幅)`（涨跌幅来自 `yfinance`）
   - 预期仓位 `= 旧仓位 ×(1+个股涨)/(1+组合涨)`
   - **主动调仓 = 实际仓位 − 预期仓位** → 正的是真加仓、负的是真减仓
   - 分类：`new / buy / sell / sold / drift`（纯被动漂移）
4. **落盘 + 展示**：写入 `holdings_history.json`、生成 `docs/index.html` 面板。
5. **推送**：通过 **Telegram Bot**（`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 存在 repo Secrets）
   推送「今日有无实质性调仓」摘要，并附上完整 HTML 报表。

---

## ⚠️ 一个踩过的坑（2026-08-04 起数据串味，已修）

**现象**：`holdings_history.json` 从 2026-08-04 起，标的 `code` 变成了中文
`"距止损 1.9%"`、`"距止损 已超"` 之类，`name` 变成 `"Unknown"`，
一直持续到本次修复。

**根因**：源网站改版，**新增了一个「交易信号面板（TradingDesk）」板块**。
它和原来的「持仓明细表（HoldingsTable）」**复用了同一个 CSS class**
`text-xs text-muted-foreground`。旧选择器 `div.text-xs.text-muted-foreground`
会把 TradingDesk 里渲染的「距止损 X%」文字也当成股票代码抓进来。

**修复**（`scripts/scraper.py` 的 `get_holdings()`）：
- **方案 A（主）**：用 HoldingsTable 每一行的 `data-loc` 属性精确定位
  （Manus 生成的站点会把 `data-loc="...HoldingsTable.tsx:72"` 渲染到真实 DOM 的行容器上），
  彻底只抓真实持仓，避开 TradingDesk。
- **方案 B（兜底）**：万一站点未来去掉 `data-loc`，保留原选择器，
  但用 `_looks_like_code()` 严格过滤掉「止损/已触发/接近」等干扰文字。

> 如果你发现 `data/holdings_history.json` 里又出现奇怪的中文 `code`，
> 第一反应是：**源网站又改版了，去 `petermoportfolio.com/` 看一眼结构**，
> 然后回到 `get_holdings()` 更新选择器。

---

## 本地运行 / 验证

```bash
pip install pandas openpyxl playwright python-docx requests yfinance
playwright install chromium

# 只跑抓取+分析（不推送，方便验证选择器是否还对）
python scripts/scraper.py
```

手动触发一次 GitHub Actions 验证线上效果：
仓库 → Actions → **Daily Portfolio Tracker** → Run workflow。

环境变量（可选，用于推送）：
- `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`

---

## 数据资产说明

- `data/holdings_history.json`：从 2026-02-07 起每天一条，是整套系统最有价值的沉淀，
  别手滑删了。
- 注意 `code` 存的是**无后缀纯数字**（港股 `00700`、A股 `600036`），
  `scraper.py` 里的 `format_ticker_for_yf()` 会在查 yfinance 时再补 `.HK` / `.SS` / `.SZ`。
