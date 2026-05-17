"""
資料來源連線測試
逐一測試每個來源是否可以抓到資料
"""

import requests
import json
import time
import yfinance as yf
from datetime import date

PASS = "✅ PASS"
FAIL = "❌ FAIL"
WARN = "⚠️  WARN"

results = []

def log(source, status, msg=""):
    line = f"{status}  [{source}] {msg}"
    print(line)
    results.append((source, status, msg))


# ─── 1. TWSE 三大法人（上市）────────────────────────────────
print("\n=== 第一層：TWSE / TPEx 官方 API ===\n")

try:
    url = "https://www.twse.com.tw/rwd/zh/fund/T86?response=json&selectType=ALLBUT0999"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()
    rows = data.get("data", [])
    if rows:
        log("TWSE 三大法人", PASS, f"共 {len(rows)} 筆，範例: {rows[0][:3]}")
    else:
        log("TWSE 三大法人", WARN, f"回應正常但 data 為空（可能非交易日）status={data.get('stat')}")
except Exception as e:
    log("TWSE 三大法人", FAIL, str(e))

time.sleep(1)

# ─── 2. TWSE 電子類股清單（上市）────────────────────────────
try:
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?response=json&type=IW"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()
    # 找電子工業
    tables = data.get("data", [])
    if tables:
        log("TWSE 電子股清單", PASS, f"共 {len(tables)} 筆，範例: {tables[0][:2]}")
    else:
        log("TWSE 電子股清單", WARN, f"data 為空，stat={data.get('stat')}")
except Exception as e:
    log("TWSE 電子股清單", FAIL, str(e))

time.sleep(1)

# ─── 3. TWSE 融資融券（上市）────────────────────────────────
try:
    url = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&selectType=MS"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()
    rows = data.get("data", [])
    if rows:
        log("TWSE 融資融券", PASS, f"共 {len(rows)} 筆，範例: {rows[0][:3]}")
    else:
        log("TWSE 融資融券", WARN, f"data 為空，stat={data.get('stat')}")
except Exception as e:
    log("TWSE 融資融券", FAIL, str(e))

time.sleep(1)

# ─── 4. TPEx 三大法人（上櫃）────────────────────────────────
try:
    today = date.today().strftime("%Y/%m/%d")
    url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d={today}&_={int(time.time()*1000)}"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()
    rows = data.get("aaData", [])
    if rows:
        log("TPEx 三大法人", PASS, f"共 {len(rows)} 筆，範例: {rows[0][:3]}")
    else:
        log("TPEx 三大法人", WARN, f"aaData 為空（可能非交易日或時間未到）")
except Exception as e:
    log("TPEx 三大法人", FAIL, str(e))

time.sleep(1)

# ─── 5. TPEx 融資融券（上櫃）────────────────────────────────
try:
    today = date.today().strftime("%Y/%m/%d")
    url = f"https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d={today}&s=0,asc&_={int(time.time()*1000)}"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    data = r.json()
    rows = data.get("aaData", [])
    if rows:
        log("TPEx 融資融券", PASS, f"共 {len(rows)} 筆")
    else:
        log("TPEx 融資融券", WARN, "aaData 為空（可能非交易日或時間未到）")
except Exception as e:
    log("TPEx 融資融券", FAIL, str(e))

time.sleep(1)

# ─── 6. yfinance（備援量價）────────────────────────────────
print("\n=== 第四層：yfinance 備援 ===\n")

try:
    t = yf.Ticker("2330.TW")
    hist = t.history(period="5d")
    if not hist.empty:
        last_close = hist["Close"].iloc[-1]
        log("yfinance 2330.TW", PASS, f"最近收盤價: {last_close:.2f}")
    else:
        log("yfinance 2330.TW", WARN, "歷史資料為空")
except Exception as e:
    log("yfinance 2330.TW", FAIL, str(e))

try:
    t = yf.Ticker("6488.TWO")
    hist = t.history(period="5d")
    if not hist.empty:
        last_close = hist["Close"].iloc[-1]
        log("yfinance 6488.TWO（上櫃）", PASS, f"最近收盤價: {last_close:.2f}")
    else:
        log("yfinance 6488.TWO", WARN, "歷史資料為空")
except Exception as e:
    log("yfinance 6488.TWO", FAIL, str(e))

# ─── 7. FinMind（需 token）────────────────────────────────
print("\n=== 第二層：FinMind API ===\n")

try:
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": "2330",
        "start_date": "2025-05-01",
        "token": "",  # 空 token 測試是否有免費額度
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    if data.get("status") == 200 and data.get("data"):
        log("FinMind TaiwanStockPrice", PASS, f"共 {len(data['data'])} 筆")
    else:
        log("FinMind TaiwanStockPrice", WARN, f"需要 token 或超出限制: {data.get('msg', '')}")
except Exception as e:
    log("FinMind TaiwanStockPrice", FAIL, str(e))

time.sleep(1)

# ─── 8. WantGoo 八大官股（爬蟲）────────────────────────────
print("\n=== 第三層：WantGoo / CMoney 爬蟲 ===\n")

try:
    url = "https://www.wantgoo.com/stock/institutional-investors/government-funds"
    r = requests.get(url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.wantgoo.com/",
    })
    if r.status_code == 200 and len(r.text) > 1000:
        log("WantGoo 八大官股", PASS, f"回應 {len(r.text)} bytes（需進一步解析）")
    else:
        log("WantGoo 八大官股", WARN, f"HTTP {r.status_code}，可能需要 JS 渲染或 Scrapling")
except Exception as e:
    log("WantGoo 八大官股", FAIL, str(e))

time.sleep(1)

# ─── 9. CMoney 籌碼K線（爬蟲）──────────────────────────────
try:
    url = "https://www.cmoney.com.tw/notice/f00008.aspx?s=2330"
    r = requests.get(url, timeout=10, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    if r.status_code == 200 and len(r.text) > 1000:
        log("CMoney 籌碼K線", PASS, f"回應 {len(r.text)} bytes（需確認分點資料是否在頁面中）")
    else:
        log("CMoney 籌碼K線", WARN, f"HTTP {r.status_code}，可能需要 Scrapling 或登入")
except Exception as e:
    log("CMoney 籌碼K線", FAIL, str(e))

# ─── 結果摘要 ───────────────────────────────────────────────
print("\n" + "="*60)
print("測試結果摘要")
print("="*60)
for src, status, msg in results:
    print(f"{status}  {src}")
