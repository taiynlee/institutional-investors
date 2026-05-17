"""
用 Scrapling 測試需要反爬的來源：
- WantGoo 八大官股（需 JS 渲染）
- CMoney 籌碼K線（中等反爬）
"""

import json
import time

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

# ─── WantGoo 八大官股 ────────────────────────────────────────
print("\n=== WantGoo 八大官股（DynamicFetcher - JS 渲染）===\n")

try:
    from scrapling.fetchers import DynamicFetcher

    page = DynamicFetcher.fetch(
        'https://www.wantgoo.com/stock/public-bank/trend',
        headless=True,
        network_idle=True,
    )
    print(f"HTTP status: {page.status}")
    print(f"頁面大小: {len(page.text)} bytes")

    # 找八大行庫表格
    rows = page.css('table tbody tr')
    if rows:
        print(f"{PASS}  [WantGoo 八大官股] 找到 {len(rows)} 列資料")
        for row in rows[:3]:
            cells = row.css('td::text').getall()
            print(f"  範例列: {cells}")
    else:
        # 試找其他資料結構
        divs = page.css('[class*="bank"]')
        items = page.css('[class*="fund"]')
        print(f"{WARN}  [WantGoo 八大官股] 無 table 結構")
        print(f"  bank class elements: {len(divs)}")
        print(f"  fund class elements: {len(items)}")
        # 印出頁面部分內容幫助 debug
        text_sample = page.css('body::text').getall()[:10]
        print(f"  頁面文字樣本: {text_sample}")

except Exception as e:
    print(f"{FAIL}  [WantGoo 八大官股] {e}")

time.sleep(2)

# ─── CMoney 籌碼K線 ──────────────────────────────────────────
print("\n=== CMoney 籌碼K線（StealthyFetcher 先試）===\n")

try:
    from scrapling.fetchers import StealthyFetcher

    page = StealthyFetcher.fetch(
        'https://www.cmoney.com.tw/notice/f00008.aspx?s=2330',
        impersonate='chrome',
        stealthy_headers=True,
    )
    print(f"HTTP status: {page.status}")
    print(f"頁面大小: {len(page.text)} bytes")

    # 找分點表格
    rows = page.css('table tr')
    if len(rows) > 3:
        print(f"{PASS}  [CMoney 籌碼K線] 找到 {len(rows)} 列")
        for row in rows[1:4]:
            cells = row.css('td::text').getall()
            if cells:
                print(f"  範例列: {cells[:5]}")
    else:
        print(f"{WARN}  [CMoney 籌碼K線] table 列數不足（{len(rows)}），可能需要 DynamicFetcher")

        # 試 DynamicFetcher
        print("\n  改用 DynamicFetcher 重試...\n")
        from scrapling.fetchers import DynamicFetcher
        page2 = DynamicFetcher.fetch(
            'https://www.cmoney.com.tw/notice/f00008.aspx?s=2330',
            headless=True,
            network_idle=True,
        )
        rows2 = page2.css('table tr')
        if len(rows2) > 3:
            print(f"{PASS}  [CMoney DynamicFetcher] 找到 {len(rows2)} 列")
            for row in rows2[1:4]:
                cells = row.css('td::text').getall()
                if cells:
                    print(f"  範例列: {cells[:5]}")
        else:
            print(f"{WARN}  [CMoney DynamicFetcher] 仍無資料，頁面大小: {len(page2.content)} bytes")

except Exception as e:
    print(f"{FAIL}  [CMoney] {e}")

# ─── WantGoo API 端點探測 ──────────────────────────────────
print("\n=== WantGoo JSON API 探測 ===\n")

try:
    from scrapling.fetchers import Fetcher

    # 試找 WantGoo 的 API endpoint（從 network request 推測）
    candidates = [
        'https://www.wantgoo.com/stock/public-bank/trend/data',
        'https://www.wantgoo.com/api/stock/public-bank',
        'https://www.wantgoo.com/stock/public-bank/GetPublicBankBuySell',
    ]
    for url in candidates:
        try:
            page = Fetcher.get(url, stealthy_headers=True)
            print(f"  {url} → HTTP {page.status}, size={len(page.text)}")
            if page.status == 200 and len(page.text) > 100:
                print(f"    內容預覽: {page.text[:200]}")
        except Exception as ex:
            print(f"  {url} → ERROR: {ex}")

except Exception as e:
    print(f"{FAIL}  [WantGoo API 探測] {e}")
