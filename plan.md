# 台股電子股主力篩選系統 — 現況架構紀錄

> 此文件記錄系統**當前實作狀態**與關鍵設計決策，作為維護參考。

---

## 目標

篩選台股上市+上櫃電子類股（約 1055 檔）中符合「主力洗盤、準備再創新高」條件的標的，以 React dashboard 呈現，並透過 LINE bot 推播每日結果。

**入場條件 = A 或 B（任一成立即列入）**

- **A（突破當日）：** BB帶寬壓縮 + 今日創30日新高 + 今日出量≥MA20×1.5 + chip_1d≥1% AND chip_12d>0 + 趨勢保護
- **B（創高後拉回）：** 近50交易日內曾創30日新高 + 今日BB位階≤5 + chip_6d≥1% AND chip_12d≥1% + 趨勢保護

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
- **戶加**（可負）：千張大戶本週持股比較上週增減%（1%=1分）

**顯示分級（不過濾）：**
- 🟢 基礎分 ≥ 80 — 積極布局
- 🟡 基礎分 60~79 — 等止跌K棒確認
- 🔴 基礎分 < 60 — 條件成立但評分不足，謹慎

---

## 排程（每日自動執行，台北時間）

| Job | 時間 | 內容 | 資料來源 |
|-----|------|------|---------|
| job1 | 16:05 | 三大法人買賣超 + 日K線量價 | TWSE T86 + MI_INDEX |
| job2 | 18:30 | 融資 + 借券賣出（同一張表） | TWSE TWT93U（欄位2-7=融資，8-12=借券） |
| job3 | 20:30（週五）| 千張大戶持股比（週報） | TDCC 集保戶股權分散表 opendata CSV（level 15） |
| job4 | 21:00 | 執行篩選計算，寫入 screening_result | 內部計算 |

> TWT93U / TWT38U 僅 09:00~20:00 可抓，非交易時間回傳 307。
> job3 改為每週五執行，非週五只記錄 skipped。

---

## 資料庫（PostgreSQL 16）

| 資料表 | 唯一鍵 | 說明 |
|--------|--------|------|
| `stock_list` | `code` | 電子股清單，含股本（張）|
| `daily_price` | `(code, trade_date)` | 日K線 OHLCV |
| `institutional` | `(code, trade_date)` | 三大法人買賣超（張） |
| `margin_trading` | `(code, trade_date)` | 融資融券餘額 |
| `securities_lending` | `(code, trade_date)` | 借券賣出餘額 |
| `shareholding` | `(code, report_date)` | 千張大戶持股（週報） |
| `screening_result` | `(code, calc_date)` | 每日篩選結果 |
| `fetch_log` | `(job_name, fetch_date)` | 執行紀錄，防重複 |

**screening_result 關鍵欄位：**
`score`（基礎分）、`dip_bonus`（資加 0~5）、`holders_bonus`（戶加，可負）、`lending_5d_chg`、`margin_5d_chg`、`bb_position`、`bb_peak`、`is_squeeze`、`vol_ratio`、`chip_ratio_6d`、`chip_ratio_12d`

> Migration 無 alembic，透過 main.py lifespan 的 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 手動執行。

---

## 已知限制與注意事項

| 事項 | 說明 |
|------|------|
| TWSE 夜間封鎖 | TWT93U 在 20:00 後回傳 HTTP 307，需交易時段才可抓（TWT38U 已廢棄，借券資料合併至 TWT93U） |
| shareholding 補填 | 首次啟動若 shareholding 表為空，自動從 TDCC bulk CSV 下載當週全市場資料（一次請求，~988 筆） |
| 大戶持股資加計算 | `holders_bonus` 依兩週 `pct_1000_lot` 差值計算；若缺少本週或上週資料則回傳 0 |
| TDCC 歷史資料限制 | TDCC open data 只提供最新一週資料，歷史週報需透過每週 job3 累積 |
| Docker 快取 | 前端程式碼更新後需 `--no-cache` 重建，否則 vite hash 相同導致舊快取被沿用 |

---

## 待處理（Backlog）

- [ ] 借券賣出歷史補填（目前只有當日資料，需選擇時間執行 90 日回填）
- [ ] CORS allow_origins 加入 `http://localhost:6174`（目前允許 3000 / 5173，前端實際跑 6174）
- [ ] v2：八大官股行庫買賣超（WantGoo，API 需 session+CSRF，待研究）
- [ ] v2：券商分點前5大買超（CMoney，URL 需修正）
