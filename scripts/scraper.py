import json
import os
import requests # 必须确保安装了 requests
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

# === 配置区域 ===
URL_HOME = "https://petermoportfolio.com/"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
HOLDINGS_FILE = os.path.join(DATA_DIR, "holdings_history.json")
LATEST_HTML = os.path.join(BASE_DIR, "docs", "index.html") # 为了让 Pages 能用，建议放 docs

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LATEST_HTML), exist_ok=True)

def get_holdings():
    """使用 Playwright 抓取最新持仓"""
    print(">>> 正在启动抓取...")
    holdings = []
    with sync_playwright() as p:
        # 服务器运行必须 headless=True
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
                    import re
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
    
    for code in all_codes:
        now = today_map.get(code)
        old = yesterday_map.get(code)
        name = now['name'] if now else old['name']
        now_share = now['share'] if now else 0.0
        old_share = old['share'] if old else 0.0
        diff = now_share - old_share
        
        if abs(diff) < 0.01: continue
        
        change_type = "hold"
        if old_share == 0: change_type = "new"
        elif now_share == 0: change_type = "sold"
        elif diff > 0: change_type = "buy"
        elif diff < 0: change_type = "sell"
        
        changes.append({
            "code": code, "name": name, "now": now_share, 
            "old": old_share, "diff": diff, "type": change_type
        })
    
    changes.sort(key=lambda x: abs(x['diff']), reverse=True)
    return changes, len(changes) > 0

def generate_html_report(date_str, today_data, changes):
    # CSS: 红色代表新进/加仓，绿色代表卖出/清仓
    css = """
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; background: #fff; }
        h2 { border-bottom: 2px solid #eee; padding-bottom: 10px; }
        .tag { padding: 3px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; color: white; display: inline-block; width: 40px; text-align: center; }
        .new { background-color: #d32f2f; } 
        .buy { background-color: #f44336; } 
        .sold { background-color: #2e7d32; } 
        .sell { background-color: #4caf50; } 
        table { width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }
        th { text-align: left; background: #f5f5f5; padding: 8px; font-size: 12px; color: #666; }
        td { padding: 8px; border-bottom: 1px solid #eee; }
        .diff-pos { color: #d32f2f; font-weight: bold; }
        .diff-neg { color: #2e7d32; font-weight: bold; }
    </style>
    """
    
    html = f"""
    <html>
    <head><meta charset="utf-8"><title>PeterPortfolio {date_str}</title>{css}</head>
    <body>
        <h2>📅 日报 ({date_str})</h2>
    """
    
    if changes:
        html += "<h3>⚡ 变动明细</h3><table><thead><tr><th>状态</th><th>股票</th><th>变动</th><th>现仓</th></tr></thead><tbody>"
        for item in changes:
            diff_str = f"{item['diff']:+.1f}%"
            diff_class = "diff-pos" if item['diff'] > 0 else "diff-neg"
            tag_map = {"new": "新进", "sold": "清仓", "buy": "加仓", "sell": "减仓"}
            html += f"""
            <tr>
                <td><span class="tag {item['type']}">{tag_map[item['type']]}</span></td>
                <td><b>{item['name']}</b><br><span style="color:#999;font-size:12px">{item['code']}</span></td>
                <td class="{diff_class}">{diff_str}</td>
                <td>{item['now']}%</td>
            </tr>
            """
        html += "</tbody></table>"
    else:
        html += "<p>✅ 今日无持仓变动。</p>"
        
    html += "<h3>📊 最新持仓</h3><table><thead><tr><th>代码</th><th>名称</th><th>仓位</th></tr></thead><tbody>"
    for item in today_data:
        html += f"<tr><td>{item['code']}</td><td>{item['name']}</td><td>{item['share']}%</td></tr>"
    html += "</tbody></table></body></html>"
    return html

def send_telegram(message, file_path=None):
    """发送 Telegram 消息和文件"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("未配置 Telegram Token，跳过发送。")
        return

    # 1. 发送文字消息
    url_msg = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url_msg, json=data)
        print("Telegram 文字消息已发送")
    except Exception as e:
        print(f"Telegram 文字发送失败: {e}")

    # 2. 发送 HTML 文件 (如果有变化)
    if file_path and os.path.exists(file_path):
        url_doc = f"https://api.telegram.org/bot{token}/sendDocument"
        try:
            with open(file_path, 'rb') as f:
                requests.post(
                    url_doc, 
                    data={"chat_id": chat_id, "caption": "📊 详细持仓日报 (点击打开)"}, 
                    files={"document": f}
                )
            print("Telegram 文件已发送")
        except Exception as e:
            print(f"Telegram 文件发送失败: {e}")

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
    
    # 保存历史
    history[today_str] = current_holdings
    save_history(history)
    
    # 保存 HTML
    with open(LATEST_HTML, 'w', encoding='utf-8') as f:
        f.write(html_report)
    
    # === 发送 Telegram ===
    # 只有当有变动时，才发送文件。如果没变动，什么都不发 (以免打扰)
    if is_changed:
        summary = f"<b>🚨 PeterPortfolio 持仓变动提醒</b>\n日期: {today_str}\n\n"
        summary += f"检测到 {len(changes)} 笔持仓变化，详情请查看下方文件 👇"
        
        print("发现变动，正在推送 Telegram...")
        send_telegram(summary, LATEST_HTML)
    else:
        print("无变动，不发送通知。")
