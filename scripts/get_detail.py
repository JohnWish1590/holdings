from playwright.sync_api import sync_playwright
import os
import time

# 保存路径
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memo_detail.html")

def get_detail_source():
    print(">>> 正在启动浏览器...")
    with sync_playwright() as p:
        # 有头模式，方便你观察
        browser = p.chromium.launch(headless=False) 
        page = browser.new_page()
        
        print(">>> 正在访问 Memos 页面...")
        page.goto("https://petermoportfolio.com/memos", timeout=60000)
        
        print(">>> 等待卡片加载...")
        page.wait_for_selector("div[data-slot='card']", timeout=60000)
        
        # === 关键动作：模拟点击第一篇笔记 ===
        print(">>> 正在点击第一篇笔记，进入详情页...")
        # 找到第一个卡片并点击
        page.locator("div[data-slot='card']").first.click()
        
        # 等待新内容加载 (假设它会打开一个模态框或跳转)
        print(">>> 等待 5 秒让完整内容加载...")
        time.sleep(5)
        
        # 保存点击后的网页代码
        content = page.content()
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(content)
            
        print("\n" + "="*50)
        print(">>> 成功！详情页源代码已保存。")
        print(f">>> 文件路径: {OUTPUT_FILE}")
        print("="*50)
        
        browser.close()

if __name__ == "__main__":
    get_detail_source()
