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
    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #333; background: #f9fafb; }
        .card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 20px; }
        h2 { border-bottom: 2px solid #eee; padding-bottom: 10px; margin-top: 0; }
        .tag { padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; color: white; display: inline-block; width: 45px; text-align: center; }
        .new { background-color: #ef4444; } 
        .buy { background-color: #f87171; } 
        .sold { background-color: #16a34a; } 
        .sell { background-color: #4ade80; } 
        .drift { background-color: #94a3b8; } 
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
        th { text-align: left; background: #f8fafc; padding: 12px 8px; font-size: 13px; color: #64748b; border-bottom: 2px solid #e2e8f0; }
        td { padding: 12px 8px; border-bottom: 1px solid #f1f5f9; }
        .diff-pos { color: #ef4444; font-weight: bold; }
        .diff-neg { color: #16a34a; font-weight: bold; }
        .sub-text { font-size: 11px; color: #94a3b8; display: block; margin-top: 2px; }
        .footer { margin-top: 20px; font-size: 12px; color: #94a3b8; text-align: center; }
    </style>
    """
    
    html = f"""
    <html>
    <head><meta charset="utf-8"><title>PeterPortfolio {date_str}</title>{css}</head>
    <body>
        <div class="card">
            <h2>📅 持仓深度解析 ({date_str})</h2>
    """
    
    if changes:
        html += """
            <p style="font-size:13px; color:#64748b; margin-bottom:15px;">
                💡 <b>说明：</b>算法已接入真实市场行情。"主动动作"剔除了股价波动影响，代表博主真正的交易行为。
            </p>
            <table>
                <thead>
                    <tr>
                        <th>诊断结论</th>
                        <th>标的名称</th>
                        <th>表面仓位变动</th>
                        <th>被动浮动<br><span class="sub-text">(股价涨跌导致)</span></th>
                        <th>⭐ 真实主动动作<br><span class="sub-text">(剔除股价影响)</span></th>
                        <th>最新仓位</th>
                    </tr>
                </thead>
                <tbody>
        """
        for item in changes:
            # 格式化数字
            total_str = f"{item['total_diff']:+.2f}%"
            active_str = f"{item['active_diff']:+.2f}%"
            passive_str = f"{item['passive_drift']:+.2f}%"
            
            # 样式调整
            t_class = "diff-pos" if item['total_diff'] > 0 else "diff-neg"
            a_class = "diff-pos" if item['active_diff'] > 0 else "diff-neg"
            p_class = "diff-pos" if item['passive_drift'] > 0 else "diff-neg"
            if abs(item['active_diff']) < 0.1: a_class = "sub-text" # 主动动作极小时变灰
            
            tag_map = {"new": "新进", "sold": "清仓", "buy": "主动买", "sell": "主动卖", "drift": "随波飘"}
            
            html += f"""
            <tr>
                <td><span class="tag {item['type']}">{tag_map[item['type']]}</span></td>
                <td><b>{item['name']}</b><br><span class="sub-text">{item['code']}</span></td>
                <td class="{t_class}">{total_str}</td>
                <td class="{p_class}">{passive_str}</td>
                <td class="{a_class}">{active_str}</td>
                <td><b>{item['now']}%</b></td>
            </tr>
            """
        html += "</tbody></table>"
    else:
        html += "<p style='padding: 15px; background: #f0fdf4; color: #166534; border-radius: 8px;'>✅ 今日未检测到博主的实质性调仓动作。</p>"
        
    html += "</div><div class='card'>"
    html += "<h3>📊 最新全局持仓分布</h3><table><thead><tr><th>代码</th><th>名称</th><th>仓位</th></tr></thead><tbody>"
    for item in today_data:
        html += f"<tr><td>{item['code']}</td><td><b>{item['name']}</b></td><td>{item['share']}%</td></tr>"
    html += f"</tbody></table></div><div class='footer'>数据获取与智能测算时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div></body></html>"
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
