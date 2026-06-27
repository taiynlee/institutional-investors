# 台股電子股主力篩選系統 — 現況架構紀錄

> 此文件記錄系統**當前實作狀態**與關鍵設計決策，作為維護參考。

---

## 目標

篩選台股上市+上櫃電子類股（約 1055 檔）中符合「主力洗盤、準備再創新高」條件的標的，以 React dashboard 呈現，並透過 LINE bot 推播每日結果。

**入場條件 = A 或 B（任一成立即列入）**

- **A（突破當日）：** BB帶寬壓縮（MA20斜率 0.3%~2.0%）+ 今日創30日新高（收盤在當日高低區間上70%以上，排除長上影線假突破）+ 今日出量≥MA20×1.5 + 突破位階>5 + chip_1d≥1% AND chip_12d>0 + 趨勢保護
- **B（創高後拉回）：** 近50交易日內曾創30日新高（突破位階>5）+ 今日BB位階 0~15（≥0 且 ≤15，跌破月線不入場）+ chip_6d≥1% AND chip_12d≥1% + 趨勢保護

**趨勢保護（硬門檻，不計分）：** MA20 > MA60 AND MA60斜率>0 AND 收盤>MA60

---

## 評分機制（基礎分 0~100）

| 維度 | 分數 | 達標條件 |
|------|------|---------|
| BB 位階 | 0~20 | 越靠近 0~2 得分越高（線性） |
| 法人6日籌碼 | +10 | chip_ratio_6d ≥ 1% |
| 法人12日籌碼 | +10 | chip_ratio_12d ≥ 1% |
| BB壓縮 | +15 | is_squeeze = True |
| 窒息量 | +10 | vol_ratio ≤ 0.5 |
| 融資不增 | +10 | margin_5d_chg ≤ 0 |
| 借券不增 | +10 | lending_5d_chg ≤ 0 |
| 大戶增加 | +10 | holders_bonus > 0（週間千張大戶增加） |
| RS 抗跌 | +5 | 個股BB降幅 < 大盤BB降幅 × 1.2 |

**額外加分（不計入基礎分）：**
- **資加**（0~5）：最近5次下跌日，法人當日淨買超→各加1分
- **戶加**（可負）：千張大戶本週 vs 上週持股人數差值（整數，正=增加，負=減少）

**顯示分級（不過濾）：**
- 🟢 基礎分 ≥ 80 — 積極布局
- 🟡 基礎分 60~79 — 等止跌K棒確認
- 🔴 基礎分 < 60 — 條件成立但評分不足，謹慎

---

## 排程（每日自動執行，台北時間）

| Job | 時間 | 內容 | 資料來源 |
|-----|------|------|---------|
| job1 | **18:00** | 三大法人買賣超 + 日K線量價 | TWSE T86 + MI_INDEX（T86 約 17:00 後穩定可用） |
| job2 | 20:45 | 融資 + 借券賣出（同一張表） | TWSE TWT93U（欄位2-7=融資，8-12=借券；TWSE 約 20:30 才更新） |
| job3 | 18:30（週日）| 千張大戶持股比（週報） | TDCC 集保戶股權分散表 opendata CSV（level 15） |
| job4 | 21:00 | 執行篩選計算，寫入 screening_result | 內部計算（支援 `target_date` 補算歷史日） |
| job5 | 每月 10-25 日 12:00 | 月營收 | MOPS（上市 + 上櫃） |
| job6 | 每季（3/1, 5/16, 8/15, 11/15）| 季報 EPS | FinMind TaiwanStockFinancialStatements |
| job7 | 每半年（1/1, 7/1）| 產業鏈分類 | ic.tpex.org.tw |
| job8 | 21:05 | 當沖候選篩選，寫入 daytrade_candidate | PG stock_pool × screener A/B 分數 |
| startup | 啟動時 | 歷史缺口補抓（最近 14 曆日） | `backfill_single_day` + job4 |
| watchdog | 每 30 分鐘 | 當日 job1/2/4/8 若未成功自動補跑 | — |

> TWT93U / TWT38U 僅 09:00~20:00 可抓，非交易時間回傳 307。
> job3 改為每週日執行（TDCC 週六處理資料，週日晚間才完成更新），非週日直接 return。
> **job4 資料守衛：** 執行前直接查 `institutional` 表確認當日有資料，若無則跳過（避免在 T86 發布前執行 job1 導致 chip_ratio_6d 算錯）。

---

## 資料庫（PostgreSQL 16 — 唯一資料庫，SQLite 已完全移除）

> `ticks.db`（fubon-dashboard 盤中 tick 快取）例外，仍為 SQLite，gitignored，僅供交易引擎盤中使用，不儲存任何持久化主資料。

| 資料表 | 唯一鍵 | 說明 |
|--------|--------|------|
| `stock_list` | `code` | 電子股清單，含股本（張）；股本來源 FinMind TaiwanStockBalanceSheet（OrdinaryShare，NTD/10/1000 轉換為張）|
| `daily_price` | `(code, trade_date)` | 日K線 OHLCV |
| `institutional` | `(code, trade_date)` | 三大法人買賣超（張） |
| `margin_trading` | `(code, trade_date)` | 融資融券餘額 |
| `securities_lending` | `(code, trade_date)` | 借券賣出餘額 |
| `shareholding` | `(code, report_date)` | 千張大戶持股（週報） |
| `screening_result` | `(code, calc_date)` | 每日篩選結果 |
| `watchlist_a` | `(code, added_date)` | 策略A追蹤清單 |
| `stock_pool` | `code` | 當沖監控股票池（139支） |
| `daytrade_candidate` | `(trade_date, code)` | 每日當沖候選（job8 篩出） |
| `daytrade_pre_session_log` | `id` | 盤前跑批紀錄 |
| `us_watchlist` | `symbol` | 美股追蹤清單 |
| `fetch_log` | `(job_name, fetch_date)` | 執行紀錄，防重複；startup_gap_backfill 依此判斷哪天缺漏 |
| `trading_settings` | `key` | 當沖引擎可調參數（key-value，15 項，即時熱重載） |

**screening_result 關鍵欄位：**
`score`（基礎分）、`dip_bonus`（資加 0~5）、`holders_bonus`（戶加，可負）、`lending_5d_chg`、`margin_5d_chg`、`bb_position`、`bb_peak`、`is_squeeze`、`vol_ratio`、`chip_ratio_6d`、`chip_ratio_12d`

> Migration 無 alembic，透過 main.py lifespan 的 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 手動執行。

---

## 已知限制與注意事項

| 事項 | 說明 |
|------|------|
| TWSE 夜間封鎖 | TWT93U 在 20:00 後回傳 HTTP 307，需交易時段才可抓（TWT38U 已廢棄，借券資料合併至 TWT93U） |
| shareholding 補填 | 首次啟動若 shareholding 表為空，自動從 TDCC bulk CSV 下載當週全市場資料（一次請求，~988 筆） |
| 大戶持股戶加計算 | `holders_bonus` 依兩週 `holders_1000_lot`（人數）差值計算（整數）；若缺少本週或上週資料則回傳 0 |
| TDCC 歷史資料限制 | TDCC open data 只提供最新一週資料，歷史週報需透過每週 job3 累積 |
| Docker 快取 | 前端程式碼更新後需重 build，`docker compose build frontend && docker compose up -d frontend` |
| chip_ratio_6d 資料完整性 | job1 若在 TWSE T86 發布前執行（系統重啟或時序異常），會存到 0 筆法人資料；job4 現已直接查 DB 確認，若當日無法人資料則跳過篩選 |
| 股本資料來源 | 使用 FinMind `TaiwanStockBalanceSheet`（`OrdinaryShare` 欄位，NTD → /10/1000 轉換為張）；`TaiwanStockInfo` 無股本欄位已廢棄。`refresh_stock_list` 只在新值 > 0 時才覆蓋，避免 API 回傳 0 誤清股本 |
| 歷史缺口補抓 | `startup_gap_backfill` 每次啟動掃最近 14 曆日，找 FetchLog 中 job1 缺失的交易日補抓；假日（0 rows）自動標記 success 跳過，不重複觸發 job4 |

---

## UI 設計規範（目前實作）

| 元件 | 顏色規則 |
|------|---------|
| 漲跌（台股慣例） | 漲=紅、跌=綠（ChipBar、走勢圖均統一） |
| 策略 badge | A=綠色、B=藍色（對應 BBGauge bar 顏色；黃色保留給退場止損籌碼警示） |
| BBGauge bar | >5=`#22c55e`綠、0~5=`#3b82f6`藍、-3~0=`#f97316`橘、<-3=`#ef4444`紅 |
| 資加（dip_bonus） | 非零=`orange-400`，零=`gray-600` |
| 戶加（holders_bonus） | 正=`sky-400`天藍、負=`pink-400`粉紅、零=`gray-500` |
| 篩選日標注 | 3日內=`green-400`（新鮮資料），超過=`gray-600` |
| 績效列顏色 | AI精選+總分第一=紫、僅AI精選=藍、僅總分第一=黃、其他=gray-900 |

---

## 當沖自動交易引擎（`services/fubon-dashboard/engine/`）

直接在 WSL 執行（非 Docker），以背景執行緒執行，由 `/engine/start|stop|status` API 控制。

### 資料流（PG-only，SQLite daily.db 已廢棄）

```
PG stock_pool + daytrade_candidate（由 job8 每日 21:05 更新）
    ↓ HTTP GET localhost:8000/api/daytrade/list  （當日標的）
    ↓ HTTP GET localhost:8000/api/pool            （股票名稱）
交易引擎啟動 → Fubon SDK → ORB 策略 → ticks.db（盤中 tick / 狀態）
```

> `ticks.db`（位於 `/home/tommy0322/fubon-data/ticks.db`）保留，儲存盤中 tick、quotes、intraday trades/positions。`daily.db` 已於 2026-06-15 刪除，所有資料改由 PG 提供。

### 交易流程

| 時段 | 動作 |
|------|------|
| 啟動時（盤前） | 呼叫 PG backend `/api/daytrade/list` 取標的；`/api/pool` 取名稱；SDK 登入；抓昨日 ATR（14日）；抓 TAIEX 昨收（日跌幅 gate） |
| 09:00–09:15（觀察期） | 每 tick 記錄，建 1min / 5min K 棒，ORB 區間鎖定（最高/最低價）|
| 09:15 後（可入場） | 每分鐘評估進場條件 |
| 13:10 | 停止新開倉 |
| 13:20 | 強制出場所有持倉 |

### 進場五條件（全部成立才下單）

| # | 條件 | 實作 |
|---|------|------|
| 1 | 突破 ORB 高點 | `price > orb_high` |
| 2 | 這分鐘量 > ORB 期均量 × 1.5 | `curr_vol >= orb_avg_vol * 1.5`（均量取 09:00-09:15 各 1min bar 平均） |
| 3 | 5min K MA5 > MA20 | 不足 5 根 5min bar 時 fallback 到 1min MA |
| 4 | 委買/總掛 ≥ 65% | `bid_total / (bid_total + ask_total) >= 0.65` |
| 5 | 大盤今日未跌超 1.5% | `(taiex_curr - taiex_昨收) / taiex_昨收 > -1.5%`（昨收取得失敗時放行） |

### 停損與張數

- **停損**：`entry_price - 1.5 × ATR`（取 ATR 止損 vs ORB 低點 - 1 tick 較寬者）
- **張數**：`總資金 × 1% ÷ (ATR × 1.5 × 1000)`，受 `max_position_capital` 上限

### 大盤熔斷（circuit breaker）

- N 分鐘（預設 5min，可 settings 覆蓋）跌幅 ≥ **1.5%** → 觸發熔斷，暫停 30 分鐘並緊急出清所有持倉
- N 分鐘漲幅 ≥ 1.5% → `surge` 狀態（期貨訊號仍可擋單）

### 出場條件（任一成立）

| 原因 | 邏輯 |
|------|------|
| ATR 止損 | `price <= stop_loss` |
| 移動停利 | 最高點回落 1%（最高點曾漲 ≥ 2% 後啟動） |
| VWAP 出場 | 成交量 < 均量 70% 且 price < VWAP |
| 停利 | 漲幅 ≥ 5%（可設定） |
| 時間止損 | 持倉超過 2h 仍未獲利 → 11:00 出場 |
| 強制出場 | 13:20 無條件出場 |

### 理論模式（Paper Trading）

每次實際評估同步執行「理論模式」，不受持倉上限限制，記錄理論損益供對照。

---

## 待處理（Backlog）

- [ ] 借券賣出歷史補填（目前只有當日資料，需選擇時間執行 90 日回填）
- [ ] CORS allow_origins 加入 `http://localhost:6174`（目前允許 3000 / 5173，前端實際跑 6174）
- [ ] 當沖篩選邏輯優化（chip_count 條件/標的數不足時顯示最高分備援）
- [ ] LINE Messaging API 月額度（200 則）滿後無法推播；每月 1 日重置，或升級 Standard plan
- [ ] v2：八大官股行庫買賣超（WantGoo，API 需 session+CSRF，待研究）
- [ ] v2：券商分點前5大買超（CMoney，URL 需修正）
- [x] 策略A追蹤清單退出機制：tracking 超過10個交易日未觸發 BB≤5 → 自動刪除，等下次重新突破再加入
- [x] 篩選器歷史缺口補抓：`startup_gap_backfill` 啟動時自動補最近 14 天
- [x] 篩選條件放寬：突破位階門檻 >8→>5，策略A MA20斜率 0.5~1.5%→0.3~2.0%
- [x] 策略A修正：require_first_day=True（只抓第一天突破，不追第二天）
- [x] 策略B修正：bb_now ≤15→≤8（位階15不是拉回，8才是回到上軌附近）；w1 ≥-0.5→≥0（大戶人數不能減少才算「主力未出場」）
- [x] 退場止損頁：移除「落榜N天」動能信號，籌碼/技術 badge 新增 tooltip 說明
- [x] 手動買賣：ManualTradePage 拆 ManualTradeContent，移入 DayTradePage 第 2 子頁（今日交易↔交易紀錄之間），頂層 Tab 移除「測試買賣」
- [x] 當沖健診：items 02/03/08/19 engine 未啟動時（no such table）改顯示告警⚠而非錯誤✘
- [x] 大盤指數：market-overview period 5d→10d，回傳 date 欄位，MarketHeader 顯示資料日期（灰色小字）
- [x] 手動買賣下單類別修正：`OrderType.DayTrade` → `OrderType.Stock`（現買/現賣），修正「沒有交易類別」錯誤
- [x] 期貨欄位修正：`futures-snapshot` endpoint 改用 `tickers(type=FUTURE)` API 取實際合約代號（FZFG6 等），30 秒 TTL cache，解決盤前 `ref_f=0` 無法建立 sym_map 問題
- [x] 引擎下單整合：`trading_engine.py` 進場/出場呼叫 `broker.buy()` / `broker.sell()`，確保 dry_run=False 時實際下單
- [x] LINE 通知整合：手動買入/賣出後透過 `claude-line-bot /notify` endpoint 推播，`LineNotifier` 優先呼叫 `LINE_BOT_URL/notify`
