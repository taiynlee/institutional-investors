# 台股當沖引擎（fubon-dashboard/engine）

## 架構概覽

```
trading_engine.py   主引擎（run() 主迴圈、信號評估、委託流程）
execution/
  broker.py         Fubon SDK 封裝（買賣/取消/條件單）
  budget.py         資金/張數計算
```

---

## 委託流程

### 買進（Option A：確認後才記持倉）

```
信號觸發 → _place_order()
  ↓ 送出限價 ROD 買單
  ↓ 存入 _chase_buys（不記持倉、不掛停損停利）

on_tick（每 tick 檢查追價）
  ↓ 現價 - 委託價 ≥ 2 tick？
    ├─ 第一次：取消舊單 → 追一次（現價 + 1 tick）
    └─ 已追過：取消舊單 → 放棄（position 未建立，無需清理）

on_filled（SDK 成交回報）
  ↓ 第一次成交 → 建倉（om.positions）+ 掛停損/停利條件單 + 通知
  ↓ 後續補單成交 → 加張數到現有持倉
  ↓ 部分成交 → 補送剩餘張數
```

### 賣出（tick 路徑：停損/停利觸發）

```
rm.on_tick() 觸發 → 送限價 ROD 賣單
  ↓ 存入 _chase_sells + _pending_sells

on_tick（每 tick 檢查追價）
  ↓ 委託價 - 現價 ≥ 2 tick？
    └─ 取消舊單 → 追低（現價 - 1 tick）→ 無限次，直到成交

on_filled（SDK 成交回報）
  ↓ 全數成交 → 清除 _chase_sells
  ↓ 部分成交 → 補送剩餘，更新 _chase_sells 張數與 order_no
```

### 強制出場（13:20 主迴圈）

```
→ 取消 _chase_sells 中的追價賣單（避免重複委託）
→ 送市價 IOC（快速出場）
→ 送備援限價 ROD（防跌停板 IOC 無人承接）
```

---

## 關鍵狀態 Dict

| Dict | 用途 |
|------|------|
| `_chase_buys` | 買單追價追蹤（含 order_no、chased 旗標） |
| `_chase_sells` | 賣單追價追蹤（無限次） |
| `_pending_buys` | 等待成交確認的買單（部分成交補單用） |
| `_pending_sells` | 等待成交確認的賣單（部分成交補單用） |
| `condition_ids` | 停損/停利觸價單 GUID（取消用） |
| `om.positions` | 已確認建立的持倉（成交後才寫入） |

---

## 追價規則

| 方向 | 觸發條件 | 追價方式 | 最大次數 |
|------|---------|---------|---------|
| 買進 | 現價 - 委託價 ≥ 2 tick | 現價 + 1 tick（向上捨入） | 1 次，失敗放棄 |
| 賣出 | 委託價 - 現價 ≥ 2 tick | 現價 - 1 tick（向下捨入） | 無限，直到成交 |

---

## 委託類型對照

| 場景 | 委託類型 | 理由 |
|------|---------|------|
| 買進（進場） | 限價 ROD | 可追價、可取消 |
| 賣出（停損/停利） | 限價 ROD | 可追價、可取消 |
| 強制出場 IOC | 市價 IOC | 最快成交 |
| 強制出場備援 | 限價 ROD | 跌停板無人接時兜底 |
| 停損條件單 | 觸價單（條件） | SDK 自動觸發 |
| 停利條件單 | 觸價單（條件） | SDK 自動觸發 |

---

## 成交回報（on_filled）

SDK 成交回報透過 `sdk.set_on_filled(_on_filled)` 註冊。

`user_def` 格式對應處理邏輯：

| user_def 前綴 | 處理 |
|--------------|------|
| `auto_buy_` | 建倉 + 掛條件單（第一次），或累加張數（後續） |
| `auto_sell_` | 確認出場；部分成交補送 |
| `auto_fe_` | 強制出場確認；有 ROD 備援，不補送 |
| `auto_lsell_` | 備援限價賣確認；部分成交補送 |

---

## 測試

```bash
# 追價邏輯（買/賣 + Option A）
python3 engine/test_chase.py

# 成交確認邏輯（部分成交補單）
python3 engine/test_fill_callback.py
```

測試不需要 SDK、不需要引擎執行，全部為 mock 環境。

---

## 處置股過濾

三重防護（TWSE TWT85U 處置股 + 全額交割股）：

1. **job8 21:05**：`sync_daytrade_list` 寫入 PG 前先拉 TWT85U 過濾
2. **引擎啟動 8:30**：`_run_inner` 再拉一次，過濾 symbols 清單，存入 `_restricted`
3. **8:55 補查**：`threading.Timer` 開盤前 5 分重拉，踢除當日新增的處置股（TWSE 有時 8:30 後才更新）
4. **`_place_order` 最後防禦**：`if symbol in _restricted: return`（兜底）

---

## WebSocket 重連機制

`FubonFeed._reconnect_stock()` 斷線時自動重連，關鍵設計：

- **重連前強制 disconnect**：`self._ws.disconnect()` 清理舊 socket 狀態，防止 `run_forever()` 拋 `"socket is already opened"` 累積死 thread
- **最小間隔 5 秒**：`_last_reconnect_ts` 記錄上次時間，若間隔 < 5s 延後執行，防止 connect→disconnect 快速循環（未修復前 4 小時可累積 2000+ 死 thread，導致 GIL 爭用假死）
- **指數退避**：首次 2s，後續加倍，上限 60s
- **`_reconnect_count` 重置**：重連成功後歸零，確保下次斷線從 2s 開始

---

## 重要時間點

| 時間 | 事件 |
|------|------|
| 08:30 | 引擎啟動，登入 SDK，訂閱 WebSocket |
| 08:55 | 處置股三次補查（TWT85U re-fetch） |
| 09:00 | 開盤，信號評估開始 |
| 09:00–13:20 | 信號評估、進出場 |
| 13:15 | 持倉預警（LINE 通知） |
| 13:20 | 強制出場（主迴圈兜底） |
| 13:30 | 收盤 |
| 13:36 | 引擎停止（DailyScheduler） |
