from playwright.sync_api import sync_playwright
import os
import time

# 保存路径
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "memos_source.html")

def save_page_source():
    print(">>> 正在启动浏览器...")
    with sync_playwright() as p:
        # 有头模式，确保页面加载逻辑正常
        browser = p.chromium.launch(headless=False) 
        page = browser.new_page()
        
        print(">>> 正在访问 Memos 页面 (等待 10 秒)...")
        try:
            page.goto("https://petermoportfolio.com/memos", timeout=60000)
            # 强制等待 10 秒，确保动态内容加载完
            page.wait_for_timeout(10000)
            
            # 模拟滚动到底部（防止懒加载）
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            
            # 获取完整 HTML
            content = page.content()
            
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write(content)
                
            print("\n" + "="*50)
            print(">>> 成功！网页源代码已保存。")
            print(f">>> 文件路径: {OUTPUT_FILE}")
            print("="*50)
            
        except Exception as e:
            print(f"出错: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    save_page_source()