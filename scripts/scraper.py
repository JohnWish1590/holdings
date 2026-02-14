import json
import os
import requests
import re
from datetime import datetime
import pandas as pd
import yfinance as yf  # 新增：用于获取真实股票行情
from playwright.sync_api import sync_playwright

# === 配置区域 ===
URL_HOME = "https://petermoportfolio.com/"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
HOLDINGS_FILE = os.path.join(DATA_DIR, "holdings_history.json")
LATEST_HTML = os.path.join(BASE_DIR, "docs", "index.html")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LATEST_HTML), exist_ok=True)

def format_ticker_for_yf(code):
    """将常见的股票代码转换为 yfinance 可识别的格式"""
    code = code.upper().strip()
    # 港股处理 (例如 0700.HK)
    if code.endswith('.HK'):
        # yfinance 港股通常是 0700.HK，如果只有 700.HK 需要补齐 4 位数字
        parts = code.split('.')
        parts[0] = parts[0].zfill(4)
        return f"{parts[0]}.HK"
    # A股处理 (简单正则推断: 6开头沪市.SS，0或3开头深市.SZ)
    if code.isdigit() and len(code) == 6:
        if code.startswith('6'): return f"{code}.SS"
        else: return f"{code}.SZ"
    return code

def get_daily_return(code):
    """获取单只股票最近一个交易日的涨跌幅 (返回小数，如 0.05 代表 5%)"""
    yf_code = format_ticker_for_yf(code)
    try:
        ticker = yf.Ticker(yf_code)
        # 获取最近两天的历史数据来计算涨跌幅
        hist = ticker.history(period="5d")
        if len(hist) >= 2:
            last_close = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            return (last_close - prev_close) / prev_close
    except Exception as e:
        print(f"无法获取 {code} ({yf_code}) 的行情数据: {e}")
    return 0.0 # 获取失败则默认没有涨跌幅（即不剥离）

def get_holdings():
    print(">>> 正在启动抓取...")
    holdings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(URL_HOME, timeout=60000)
            page.wait_for_selector("div.text-muted-foreground", timeout=60000)
            
            elements = page.locator("div.text-xs.text-muted-foreground").all()
            for el in elements:
                code = el.inner_text().strip()
                if not code or len(code) > 8: continue
                try: name = el.locator("xpath=..//span[contains(@class, 'font-semibold')]").inner_text()
                except: name = "Unknown"
                share = 0.0
                try:
                    row_text = el.locator("xpath=../..").inner_text()
                    match = re.search(r'(\d+\.?\d*)%', row_text)
                    if match: share = float(match.group(1))
                except: pass

                holdings.append({"code": code, "name": name, "share": share})
        except Exception as e:
            print(f"抓取失败: {e}")
        browser.close()
    
    holdings.sort(key=lambda x: x['share'], reverse=True)
    return holdings

def load_history():
    if os.path.exists(HOLDINGS_FILE):
        with open(HOLDINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_history(history_data):
    with open(HOLDINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

def compare_holdings(today_data, yesterday_data):
    changes = []
    today_map = {item['code']: item for item in today_data}
    yesterday_map = {item['code']: item for item in yesterday_data}
    all_codes = set(today_map.keys()) | set(yesterday_map.keys())
    
    # --- 核心数学逻辑：计算漂移与主动调仓 ---
    print(">>> 正在拉取行情，计算真实调仓...")
    
    # 1. 批量获取昨日股票涨跌幅
    stock_returns = {}
    for code in all_codes:
        stock_returns[code] = get_daily_return(code)
        
    # 2. 计算整个组合的理论总收益率 (Total Portfolio Return)
    # R_p = sum(W_old * R_i)
    portfolio_return = 0.0
    for code, old_item in yesterday_map.items():
        weight_old_decimal = old_item['share'] / 100.0
        portfolio_return += weight_old_decimal * stock_returns[code]
        
    # 3. 逐个计算“预期仓位”和“主动调仓”
    for code in all_codes:
        now = today_map.get(code)
        old = yesterday_map.get(code)
        
        name = now['name'] if now else old['name']
        now_share = now['share'] if now else 0.0
        old_share = old['share'] if old else 0.0
        total_diff = now_share - old_share
        
        # 预期自然漂移仓位 = 旧仓位 * (1 + 股票涨幅) / (1 + 组合总涨幅)
        if old_share > 0:
            expected_share = old_share * (1 + stock_returns[code]) / (1 + portfolio_return)
        else:
            expected_share = 0.0
            
        # 真正的“主动交易” = 现在的实际仓位 - 没做交易情况下的预期仓位
        active_diff = now_share - expected_share
        passive_drift = total_diff - active_diff
        
        # 过滤掉极小的误差 (比如 0.1% 以内的变动我们认为可能只是四舍五入)
        if abs(total_diff) < 0.1 and abs(active_diff) < 0.2:
            continue
            
        change_type = "hold"
        if old_share == 0: change_type = "new"
        elif now_share == 0: change_type = "sold"
        elif active_diff > 0.15: change_type = "buy"   # 阈值：主动加仓超过 0.15% 才算buy
        elif active_diff < -0.15: change_type = "sell" # 阈值：主动减仓超过 0.15% 才算sell
        else:
            # 如果只是跟着市场飘，或者调仓极小，就不算核心变动
            if abs(total_diff) < 0.5: 
                continue 
            change_type = "drift" # 纯粹是被动漂移
        
        changes.append({
            "code": code, 
            "name": name, 
            "now": now_share, 
            "old": old_share, 
            "total_diff": total_diff,
            "active_diff": active_diff,   # 真正的买卖动作
            "passive_drift": passive_drift, # 股价涨跌造成的假象
            "type": change_type
        })
    
    # 优先按主动调仓的绝对值排序，把博主真正的动作排在前面
    changes.sort(key=lambda x: abs(x['active_diff']), reverse=True)
    return changes, len(changes) > 0

def generate_html_report(date_str, today_data, changes):
    # 动态计算图表的比例尺（找出今天最大的主动调仓幅度，作为 100% 宽度）
    max_active = max([abs(c['active_diff']) for c in changes] + [0.1]) if changes else 0.1
    max_passive = max([abs(c['passive_drift']) for c in changes] + [0.1]) if changes else 0.1

    css = """
    <style>
        :root { --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --sub: #64748b; --border: #e2e8f0; 
                --buy: #ef4444; --buy-light: #fee2e2; --sell: #10b981; --sell-light: #d1fae5; 
                --drift: #94a3b8; --weight-bg: #e0e7ff; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
               max-width: 950px; margin: 0 auto; padding: 20px; color: var(--text); background: var(--bg); }
        .card { background: var(--card); border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); margin-bottom: 24px; }
        h2 { margin-top: 0; border-bottom: 2px solid var(--border); padding-bottom: 12px; font-size: 20px; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 10px; }
        th { text-align: center; padding: 12px 8px; font-weight: 600; color: var(--sub); border-bottom: 2px solid var(--border); }
        th:first-child, td:first-child { text-align: left; }
        td { padding: 12px 8px; border-bottom: 1px solid var(--border); text-align: center; vertical-align: middle; }
        
        /* 标的名称列 */
        .stock-name { font-weight: 600; font-size: 15px; }
        .stock-code { font-size: 12px; color: var(--sub); margin-top: 2px; display: block; }
        
        /* 正负向柱状图容器 */
        .dv-bar-container { display: flex; align-items: center; justify-content: center; width: 100%; max-width: 140px; margin: 0 auto; }
        .dv-left, .dv-right { flex: 1; display: flex; height: 16px; align-items: center; }
        .dv-left { justify-content: flex-end; padding-right: 4px; border-right: 1px solid #cbd5e1; }
        .dv-right { justify-content: flex-start; padding-left: 4px; border-left: 1px solid #cbd5e1; margin-left: -1px; }
        
        /* 柱子本体 */
        .bar-sell { height: 12px; background: var(--sell); border-radius: 2px 0 0 2px; }
        .bar-buy { height: 12px; background: var(--buy); border-radius: 0 2px 2px 0; }
        .bar-drift { height: 6px; background: var(--drift); border-radius: 2px; opacity: 0.3; }
        
        /* 数据标签 */
        .val-buy { color: var(--buy); font-weight: bold; }
        .val-sell { color: var(--sell); font-weight: bold; }
        .val-drift { color: var(--sub); font-size: 12px; }
        
        /* 仓位水位线 */
        .weight-cell { position: relative; text-align: right !important; padding-right: 15px !important; font-weight: bold; font-family: monospace; font-size: 15px; }
        .weight-bg { position: absolute; left: 0; top: 10%; height: 80%; background: var(--weight-bg); z-index: 0; border-radius: 4px; opacity: 0.6; }
        .weight-text { position: relative; z-index: 1; }
        
        /* 弱化未操作的行 */
        .row-passive { opacity: 0.6; filter: grayscale(50%); transition: all 0.2s; }
        .row-passive:hover { opacity: 1; filter: grayscale(0%); background: #f8fafc; }
        
        .footer { text-align: center; font-size: 12px; color: var(--sub); margin-top: 20px; }
    </style>
    """
    
    html = f"""
    <html>
    <head><meta charset="utf-8"><title>PeterPortfolio 监控面板</title>{css}</head>
    <body>
        <div class="card">
            <h2>🎯 真实调仓 X光机 ({date_str})</h2>
            <p style="font-size:13px; color:var(--sub); margin-bottom:20px;">
                * 图形化剥离市场波动。<b>彩色粗条</b>代表博主真实交易，向右(红)为买，向左(绿)为卖。
            </p>
    """
    
    if changes:
        html += """
            <table>
                <thead>
                    <tr>
                        <th style="width: 25%;">标的</th>
                        <th style="width: 20%;">🌊 被动漂移 (受股价影响)</th>
                        <th style="width: 35%;">⭐ 真实主动动作 (剔除涨跌)</th>
                        <th style="width: 20%; text-align: right; padding-right: 15px;">最新仓位</th>
                    </tr>
                </thead>
                <tbody>
        """
        for item in changes:
            is_active = item['type'] in ['buy', 'sell', 'new', 'sold']
            row_class = "" if is_active else "row-passive"
            
            # 1. 计算主动动作柱状图宽度
            act_val = item['active_diff']
            act_width = min((abs(act_val) / max_active) * 100, 100)
            
            if act_val > 0.15: # 加仓
                act_html = f"""
                <div class="dv-bar-container">
                    <div class="dv-left"></div>
                    <div class="dv-right"><div class="bar-buy" style="width: {act_width}%;"></div></div>
                </div>
                <div class="val-buy">+{act_val:.2f}%</div>
                """
            elif act_val < -0.15: # 减仓
                act_html = f"""
                <div class="dv-bar-container">
                    <div class="dv-left"><div class="bar-sell" style="width: {act_width}%;"></div></div>
                    <div class="dv-right"></div>
                </div>
                <div class="val-sell">{act_val:.2f}%</div>
                """
            else: # 无明显动作
                act_html = f'<div class="val-drift">未见操作 ({act_val:+.2f}%)</div>'

            # 2. 计算被动漂移柱状图宽度 (做得更细更浅，作为辅助参考)
            pas_val = item['passive_drift']
            pas_width = min((abs(pas_val) / max_passive) * 100, 100)
            
            if pas_val > 0:
                pas_html = f'<div class="dv-bar-container"><div class="dv-left"></div><div class="dv-right"><div class="bar-drift" style="width:{pas_width}%; background:var(--buy);"></div></div></div><div class="val-drift">+{pas_val:.2f}%</div>'
            else:
                pas_html = f'<div class="dv-bar-container"><div class="dv-left"><div class="bar-drift" style="width:{pas_width}%; background:var(--sell);"></div></div><div class="dv-right"></div></div><div class="val-drift">{pas_val:.2f}%</div>'

            # 3. 计算最新仓位的水位线背景
            weight = item['now']
            
            html += f"""
            <tr class="{row_class}">
                <td>
                    <span class="stock-name">{item['name']}</span>
                    <span class="stock-code">{item['code']}</span>
                </td>
                <td>{pas_html}</td>
                <td>{act_html}</td>
                <td class="weight-cell">
                    <div class="weight-bg" style="width: {weight}%;"></div>
                    <span class="weight-text">{weight:.2f}%</span>
                </td>
            </tr>
            """
        html += "</tbody></table>"
    else:
        html += "<div style='padding: 20px; text-align: center; color: var(--sell); background: var(--sell-light); border-radius: 8px;'>🍵 今日大盘风平浪静，未检测到任何实质性调仓。</div>"
        
    html += "</div><div class='card'>"
    html += "<h2>📊 完整大盘阵型</h2><table><thead><tr><th>标的</th><th style='text-align:right; padding-right:15px;'>总配比</th></tr></thead><tbody>"
    for item in today_data:
        html += f"""
        <tr>
            <td><b>{item['name']}</b> <span style="color:#94a3b8;font-size:12px;margin-left:8px;">{item['code']}</span></td>
            <td class="weight-cell">
                <div class="weight-bg" style="width: {item['share']}%;"></div>
                <span class="weight-text">{item['share']}%</span>
            </td>
        </tr>
        """
    html += f"</tbody></table></div><div class='footer'>🤖 量化引擎更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div></body></html>"
    return html

def send_telegram(message, file_path=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    url_msg = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url_msg, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
    except: pass

    if file_path and os.path.exists(file_path):
        url_doc = f"https://api.telegram.org/bot{token}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                requests.post(url_doc, data={"chat_id": chat_id, "caption": "📈 深度测算报表 (点开查看剥离数据)"}, files={"document": f})
        except: pass

if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    current_holdings = get_holdings()
    
    if not current_holdings:
        exit(1)
        
    history = load_history()
    last_date = sorted(history.keys())[-1] if history else None
    last_holdings = history[last_date] if last_date else []
    
    changes, is_changed = compare_holdings(current_holdings, last_holdings)
    html_report = generate_html_report(today_str, current_holdings, changes)
    
    history[today_str] = current_holdings
    save_history(history)
    with open(LATEST_HTML, 'w', encoding='utf-8') as f:
        f.write(html_report)
    
    # 过滤出真正有主动买卖动作的标的（排除仅仅是被动漂移的）
    active_changes = [c for c in changes if c['type'] in ['buy', 'sell', 'new', 'sold']]
    
    summary = f"<b>🤖 PeterPortfolio 深度监控报告</b>\n日期: {today_str}\n\n"
    
    if active_changes:
        summary += f"🚨 <b>核心诊断：发现 {len(active_changes)} 笔实质性调仓</b>\n"
        summary += "已通过算法剔除股价自然涨跌干扰。\n\n"
        for c in active_changes[:3]: # Telegram预览最多显示3个最关键的动作
            action = "加仓" if c['active_diff'] > 0 else "减仓"
            if c['type'] == 'new': action = "建仓"
            if c['type'] == 'sold': action = "清仓"
            summary += f"▪️ {c['name']}: {action} 约 {abs(c['active_diff']):.2f}%\n"
        if len(active_changes) > 3:
            summary += "...\n\n"
        summary += "👇 点击下方报表查看所有真实买卖明细"
    else:
        summary += "✅ <b>核心诊断：未见实质性动作</b>\n今日仓位变化主要为市场波动的自然漂移，博主并未进行明显的主动买卖。\n👇 点击文件查看详细数据"

    print("正在推送 Telegram...")
    send_telegram(summary, LATEST_HTML)
