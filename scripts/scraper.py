import json
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

# === 配置区域 ===
URL_HOME = "https://petermoportfolio.com/"
# 数据保存路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
HOLDINGS_FILE = os.path.join(DATA_DIR, "holdings_history.json") # 总历史记录
LATEST_HTML = os.path.join(DATA_DIR, "index.html") # 生成的网站首页

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)

def get_holdings():
    """使用 Playwright 抓取最新持仓"""
    print(">>> 正在启动抓取...")
    holdings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(URL_HOME, timeout=60000)
            page.wait_for_selector("div.text-muted-foreground", timeout=60000)
            
            # 抓取逻辑 (复用之前的稳健逻辑)
            elements = page.locator("div.text-xs.text-muted-foreground").all()
            for el in elements:
                code = el.inner_text().strip()
                if not code or len(code) > 8: continue
                
                # 找名字
                try: name = el.locator("xpath=..//span[contains(@class, 'font-semibold')]").inner_text()
                except: name = "Unknown"
                
                # 找比例
                share = 0.0
                try:
                    row_text = el.locator("xpath=../..").inner_text()
                    import re
                    match = re.search(r'(\d+\.?\d*)%', row_text)
                    if match: share = float(match.group(1))
                except: pass

                holdings.append({
                    "code": code,
                    "name": name,
                    "share": share
                })
        except Exception as e:
            print(f"抓取失败: {e}")
        browser.close()
    
    # 按比例从大到小排序
    holdings.sort(key=lambda x: x['share'], reverse=True)
    return holdings

def load_history():
    """读取历史数据"""
    if os.path.exists(HOLDINGS_FILE):
        with open(HOLDINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_history(history_data):
    """保存历史数据"""
    with open(HOLDINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=2)

def compare_holdings(today_data, yesterday_data):
    """
    核心功能：对比持仓变化
    返回: changes (变化列表), is_changed (是否有变)
    """
    changes = []
    # 转成字典方便查询 {code: share}
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
        
        # 忽略极小的浮点数误差
        if abs(diff) < 0.01: continue
        
        change_type = "hold"
        if old_share == 0: change_type = "new"      # 新建仓
        elif now_share == 0: change_type = "sold"   # 清仓
        elif diff > 0: change_type = "buy"          # 加仓
        elif diff < 0: change_type = "sell"         # 减仓
        
        changes.append({
            "code": code,
            "name": name,
            "now": now_share,
            "old": old_share,
            "diff": diff,
            "type": change_type
        })
    
    # 按变化幅度排序
    changes.sort(key=lambda x: abs(x['diff']), reverse=True)
    return changes, len(changes) > 0

def generate_html_report(date_str, today_data, changes):
    """生成漂亮的 HTML 报告 (用于网页展示和邮件)"""
    
    # CSS 样式：红涨绿跌 (或者你可以反过来，这里用红色表示买入/新增)
    css = """
    <style>
        body { font-family: 'Microsoft YaHei', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }
        h2 { border-bottom: 2px solid #eee; padding-bottom: 10px; }
        .tag { padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: bold; color: white; }
        .new { background-color: #d32f2f; } /* 鲜红: 新进 */
        .buy { background-color: #f44336; } /* 浅红: 加仓 */
        .sold { background-color: #388e3c; } /* 深绿: 清仓 */
        .sell { background-color: #4caf50; } /* 浅绿: 减仓 */
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th { text-align: left; background: #f5f5f5; padding: 10px; }
        td { padding: 10px; border-bottom: 1px solid #eee; }
        .diff-pos { color: #d32f2f; font-weight: bold; }
        .diff-neg { color: #388e3c; font-weight: bold; }
        .footer { margin-top: 30px; font-size: 12px; color: #999; }
    </style>
    """
    
    html = f"""
    <html>
    <head><meta charset="utf-8"><title>PeterPortfolio 监控日报 {date_str}</title>{css}</head>
    <body>
        <h2>📅 监控日报 ({date_str})</h2>
    """
    
    # 1. 如果有变化，显示变化表
    if changes:
        html += "<h3>⚡ 重点变动</h3><table><thead><tr><th>类型</th><th>股票</th><th>变动</th><th>现仓位</th></tr></thead><tbody>"
        for item in changes:
            diff_str = f"{item['diff']:+.1f}%"
            diff_class = "diff-pos" if item['diff'] > 0 else "diff-neg"
            
            tag_name = {"new": "新进", "sold": "清仓", "buy": "加仓", "sell": "减仓"}[item['type']]
            tag_class = item['type']
            
            html += f"""
            <tr>
                <td><span class="tag {tag_class}">{tag_name}</span></td>
                <td>{item['name']} ({item['code']})</td>
                <td class="{diff_class}">{diff_str}</td>
                <td>{item['now']}%</td>
            </tr>
            """
        html += "</tbody></table>"
    else:
        html += "<p style='color: #999;'>✅ 今日无持仓变动。</p>"
        
    # 2. 显示当前完整持仓
    html += "<h3>📊 当前最新持仓</h3><table><thead><tr><th>代码</th><th>名称</th><th>仓位</th></tr></thead><tbody>"
    for item in today_data:
        html += f"<tr><td>{item['code']}</td><td>{item['name']}</td><td>{item['share']}%</td></tr>"
    html += "</tbody></table>"
    
    html += f"<div class='footer'>更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div></body></html>"
    return html

def send_email(subject, html_content):
    """发送 HTML 邮件"""
    # 从环境变量读取配置 (需要在 GitHub Secrets 里设置)
    smtp_server = "smtp.qq.com" # 如果是 QQ 邮箱
    smtp_port = 465
    sender = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS") # 授权码，不是密码
    receiver = os.environ.get("EMAIL_TO")
    
    if not sender or not password:
        print("未配置邮箱，跳过发送。")
        return

    msg = MIMEText(html_content, 'html', 'utf-8')
    msg['From'] = Header("PortfolioBot", 'utf-8')
    msg['To'] = Header("Investor", 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')

    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print("邮件发送成功！")
    except Exception as e:
        print(f"邮件发送失败: {e}")

if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. 获取数据
    current_holdings = get_holdings()
    if not current_holdings:
        print("抓取失败，终止。")
        exit(1)
        
    # 2. 读取历史并对比
    history = load_history()
    # 获取"昨天"的数据（其实就是历史记录里最近的一天）
    last_date = sorted(history.keys())[-1] if history else None
    last_holdings = history[last_date] if last_date else []
    
    changes, is_changed = compare_holdings(current_holdings, last_holdings)
    
    # 3. 生成报告
    html_report = generate_html_report(today_str, current_holdings, changes)
    
    # 4. 保存数据
    # A. 更新 JSON 数据库
    history[today_str] = current_holdings
    save_history(history)
    
    # B. 保存 HTML 文件 (GitHub Pages 会展示这个)
    with open(LATEST_HTML, 'w', encoding='utf-8') as f:
        f.write(html_report)
    
    # 5. 发送通知 (只有变化时发送)
    if is_changed:
        print("发现变化！正在发送邮件...")
        send_email(f"【持仓变动】PeterPortfolio {today_str}", html_report)
    else:
        print("持仓无变化，不打扰。")
