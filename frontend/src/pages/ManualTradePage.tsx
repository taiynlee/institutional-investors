import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

const API = '/fubon-api'

interface PoolStock { code: string; name: string }
interface ManualPos {
  symbol: string
  entry_price: number
  lots: number
  stop_loss: number
  take_profit: number
  stop_guid: string | null
  tp_guid: string | null
  prev_close: number
  entry_time: string
  curr_price: number
  unrealized: number | null
}

function tw_tick_size(price: number): number {
  if (price < 10) return 0.01
  if (price < 50) return 0.05
  if (price < 100) return 0.1
  if (price < 500) return 0.5
  if (price < 1000) return 1.0
  return 5.0
}
function round_up_tick(price: number): number {
  const t = tw_tick_size(price)
  return Math.ceil(Math.round(price / t * 1e8) / 1e8) * t
}
function round_down_tick(price: number): number {
  const t = tw_tick_size(price)
  return Math.floor(Math.round(price / t * 1e8) / 1e8) * t
}

export function ManualTradePage() {
  const [pool, setPool] = useState<PoolStock[]>([])
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [prevClose, setPrevClose] = useState('')
  const [lots, setLots] = useState(1)
  const [stopTicks, setStopTicks] = useState(4)
  const [tpAddPct, setTpAddPct] = useState(4.0)
  const [positions, setPositions] = useState<ManualPos[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [showDropdown, setShowDropdown] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  const loadPool = () =>
    axios.get<PoolStock[]>('/api/pool').then(r => setPool(r.data)).catch(() => {})
  const loadPositions = () =>
    axios.get<ManualPos[]>(`${API}/manual-trade/positions`).then(r => setPositions(r.data)).catch(() => {})

  useEffect(() => {
    loadPool()
    loadPositions()
    const t = setInterval(loadPositions, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node))
        setShowDropdown(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const filtered = pool.filter(s =>
    symbol.length >= 1 &&
    (s.code.includes(symbol) || s.name.includes(symbol))
  ).slice(0, 8)

  const entryPrice = parseFloat(price) || 0
  const refClose = parseFloat(prevClose) || entryPrice
  const ts = entryPrice > 0 ? tw_tick_size(entryPrice) : 0
  const stopLoss = entryPrice > 0 ? round_up_tick(entryPrice - stopTicks * ts) : 0
  const entryChg = refClose > 0 ? (entryPrice - refClose) / refClose * 100 : 0
  const takeProfit = refClose > 0
    ? round_down_tick(refClose * (1 + (entryChg + tpAddPct) / 100))
    : 0

  const fetchPrice = async () => {
    if (!symbol) return
    try {
      const r = await axios.get(`${API}/manual-trade/price/${symbol}`)
      if (r.data.price > 0) setPrice(String(r.data.price))
      else setMsg({ ok: false, text: '引擎無此股報價，請手動輸入價格' })
    } catch {
      setMsg({ ok: false, text: '無法取得報價（引擎未啟動？）' })
    }
  }

  const doBuy = async (forceMarket = false) => {
    if (!symbol || entryPrice <= 0) {
      setMsg({ ok: false, text: '請選擇股票並輸入價格' })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const r = await axios.post(`${API}/manual-trade/buy`, null, {
        params: {
          symbol,
          lots,
          price: entryPrice,
          prev_close: refClose,
          stop_loss_ticks: stopTicks,
          take_profit_add_pct: tpAddPct,
          force_market: forceMarket,
        },
      })
      setMsg({ ok: true, text: `✓ ${symbol} 買進 ${lots}張 @ ${entryPrice}` })
      setSymbol('')
      setName('')
      setPrice('')
      setPrevClose('')
      loadPositions()
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally {
      setBusy(false)
    }
  }

  const doSell = async (sym: string) => {
    if (!confirm(`確定市價賣出 ${sym}？同時取消兩張觸價單。`)) return
    setBusy(true)
    try {
      const r = await axios.post(`${API}/manual-trade/sell/${sym}`)
      const pnl = r.data.pnl
      setMsg({ ok: pnl >= 0, text: `✓ ${sym} 已出場，損益 ${pnl >= 0 ? '+' : ''}${Number(pnl).toLocaleString()}` })
      loadPositions()
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally {
      setBusy(false)
    }
  }

  const doCancelConditions = async (sym: string) => {
    try {
      await axios.post(`${API}/manual-trade/cancel-conditions/${sym}`)
      setMsg({ ok: true, text: `✓ ${sym} 觸價單已取消` })
      loadPositions()
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    }
  }

  const doDeleteRecord = async (sym: string) => {
    await axios.delete(`${API}/manual-trade/position/${sym}`).catch(() => {})
    loadPositions()
  }

  const card = 'bg-gray-900 border border-gray-800 rounded-xl p-5'
  const lbl = 'text-xs text-gray-500 mb-1 block'
  const inp = 'bg-gray-800 border border-gray-700 text-white rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 w-full'

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-black text-white">手動下單</h1>
          <p className="text-gray-400 text-sm mt-0.5">真實下單 · 自動掛停損/停利觸價單</p>
        </div>

        {msg && (
          <div className={`text-sm px-4 py-3 rounded-lg ${msg.ok ? 'bg-green-900 text-green-300 border border-green-700' : 'bg-red-900 text-red-300 border border-red-700'}`}>
            {msg.text}
          </div>
        )}

        {/* 下單面板 */}
        <div className={card}>
          <div className="text-sm font-semibold text-gray-300 mb-4">新增買進</div>
          <div className="grid grid-cols-2 gap-4">
            {/* 股票選擇 */}
            <div className="col-span-2" ref={dropRef}>
              <label className={lbl}>股票（pool 內）</label>
              <div className="relative">
                <input
                  className={inp}
                  value={symbol}
                  onChange={e => { setSymbol(e.target.value); setShowDropdown(true) }}
                  placeholder="輸入代碼或名稱"
                />
                {showDropdown && filtered.length > 0 && (
                  <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg overflow-hidden shadow-xl">
                    {filtered.map(s => (
                      <button
                        key={s.code}
                        onClick={() => {
                          setSymbol(s.code)
                          setName(s.name)
                          setShowDropdown(false)
                        }}
                        className="w-full text-left px-4 py-2 hover:bg-gray-700 flex gap-3 items-center"
                      >
                        <span className="font-mono text-blue-300 w-14">{s.code}</span>
                        <span className="text-gray-300">{s.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {name && <div className="text-xs text-gray-500 mt-1">{name}</div>}
            </div>

            {/* 買進價 */}
            <div>
              <label className={lbl}>買進價格（限價）</label>
              <div className="flex gap-2">
                <input
                  className={inp}
                  type="number"
                  value={price}
                  onChange={e => setPrice(e.target.value)}
                  placeholder="例：250.5"
                  step="0.01"
                />
                <button
                  onClick={fetchPrice}
                  className="shrink-0 px-3 py-2 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded border border-gray-600"
                  title="從引擎取最新報價"
                >
                  最新報價
                </button>
              </div>
            </div>

            {/* 昨收 */}
            <div>
              <label className={lbl}>昨收（計算停利用）</label>
              <input
                className={inp}
                type="number"
                value={prevClose}
                onChange={e => setPrevClose(e.target.value)}
                placeholder="若空白則以買進價代替"
                step="0.01"
              />
            </div>

            {/* 張數 */}
            <div>
              <label className={lbl}>張數</label>
              <input
                className={inp}
                type="number"
                value={lots}
                onChange={e => setLots(Math.max(1, parseInt(e.target.value) || 1))}
                min={1}
              />
            </div>

            {/* 停損 ticks */}
            <div>
              <label className={lbl}>停損 tick 數</label>
              <input
                className={inp}
                type="number"
                value={stopTicks}
                onChange={e => setStopTicks(Math.max(1, parseInt(e.target.value) || 4))}
                min={1}
              />
            </div>

            {/* 停利加碼% */}
            <div>
              <label className={lbl}>停利附加漲幅 %</label>
              <input
                className={inp}
                type="number"
                value={tpAddPct}
                onChange={e => setTpAddPct(parseFloat(e.target.value) || 4)}
                step={0.5}
                min={0.5}
              />
            </div>
          </div>

          {/* 預覽觸價單 */}
          {entryPrice > 0 && (
            <div className="mt-4 bg-gray-800 rounded-lg p-4 space-y-3 text-sm">
              <div className="text-gray-400 font-semibold text-xs uppercase tracking-wide mb-2">觸價單預覽</div>

              <div className="flex items-start gap-3">
                <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-bold bg-red-900 text-red-300 border border-red-700 mt-0.5">停損</span>
                <div>
                  <div className="text-white">
                    成交價 ≤ <span className="font-mono text-red-300">{stopLoss.toFixed(2)}</span>
                  </div>
                  <div className="text-gray-500 text-xs mt-0.5">
                    = 買進價 {entryPrice} − {stopTicks} tick（{(ts).toFixed(2)}）= {(entryPrice - stopTicks * ts).toFixed(2)} → 向上捨入 tick<br />
                    觸發條件達成 → 全數<span className="text-orange-300">市價賣出</span>（ROD，當日有效）
                  </div>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <span className="shrink-0 px-2 py-0.5 rounded text-[10px] font-bold bg-green-900 text-green-300 border border-green-700 mt-0.5">停利</span>
                <div>
                  <div className="text-white">
                    成交價 ≥ <span className="font-mono text-green-300">{takeProfit.toFixed(2)}</span>
                  </div>
                  <div className="text-gray-500 text-xs mt-0.5">
                    = 昨收 {refClose.toFixed(2)} × (1 + ({entryChg.toFixed(1)}% 進場漲幅 + {tpAddPct}% 加碼)) → 向下捨入 tick<br />
                    觸發條件達成 → 全數<span className="text-orange-300">市價賣出</span>（ROD，當日有效）
                  </div>
                </div>
              </div>

              <div className="text-xs text-yellow-600 border-t border-gray-700 pt-2 mt-1">
                ⚠ 兩張觸價單同時掛出，任一觸發後另一張需手動取消（富邦平台不支援 OCO）
              </div>
            </div>
          )}

          {/* 下單按鈕 */}
          <div className="flex gap-3 mt-5">
            <button
              onClick={() => doBuy(false)}
              disabled={busy || !symbol || entryPrice <= 0}
              className="flex-1 py-2.5 bg-red-700 hover:bg-red-600 text-white font-bold rounded-lg disabled:opacity-40"
            >
              {busy ? '下單中...' : `限價買進 ${lots}張`}
            </button>
            <button
              onClick={() => doBuy(true)}
              disabled={busy || !symbol}
              className="px-5 py-2.5 bg-orange-800 hover:bg-orange-700 text-white text-sm font-bold rounded-lg disabled:opacity-40"
              title="市價 IOC，強制成交"
            >
              市價強制買
            </button>
          </div>
        </div>

        {/* 持倉列表 */}
        {positions.length > 0 && (
          <div className={card}>
            <div className="text-sm font-semibold text-gray-300 mb-4">手動持倉（{positions.length}）</div>
            <div className="space-y-4">
              {positions.map(pos => {
                const pnlClass = pos.unrealized == null ? 'text-gray-500'
                  : pos.unrealized >= 0 ? 'text-red-400' : 'text-green-400'
                return (
                  <div key={pos.symbol} className="bg-gray-800 rounded-lg p-4 space-y-2">
                    <div className="flex justify-between items-start">
                      <div>
                        <span className="font-mono text-blue-300 font-bold text-base">{pos.symbol}</span>
                        <span className="text-gray-400 text-sm ml-2">{pos.lots}張 @ {pos.entry_price}</span>
                        <span className="text-gray-600 text-xs ml-2">{pos.entry_time}</span>
                      </div>
                      <div className={`font-bold text-base ${pnlClass}`}>
                        {pos.unrealized != null
                          ? `${pos.unrealized >= 0 ? '+' : ''}${pos.unrealized.toLocaleString('zh-TW', { maximumFractionDigits: 0 })}`
                          : '—'}
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div className="bg-gray-900 rounded p-2">
                        <div className="text-gray-500 mb-0.5">停損觸價單</div>
                        <div className="text-red-300 font-mono font-bold">≤ {pos.stop_loss.toFixed(2)}</div>
                        <div className="text-gray-600 mt-0.5">{pos.stop_guid ? `已掛 ${pos.stop_guid.slice(0, 8)}…` : '未掛出'}</div>
                      </div>
                      <div className="bg-gray-900 rounded p-2">
                        <div className="text-gray-500 mb-0.5">停利觸價單</div>
                        <div className="text-green-300 font-mono font-bold">≥ {pos.take_profit.toFixed(2)}</div>
                        <div className="text-gray-600 mt-0.5">{pos.tp_guid ? `已掛 ${pos.tp_guid.slice(0, 8)}…` : '未掛出'}</div>
                      </div>
                    </div>

                    {pos.curr_price > 0 && (
                      <div className="text-xs text-gray-500">
                        現價 <span className="text-white font-mono">{pos.curr_price.toFixed(2)}</span>
                        <span className="ml-3">進場價 {pos.entry_price} → 昨收 {pos.prev_close.toFixed(2)}</span>
                      </div>
                    )}

                    <div className="flex gap-2 pt-1">
                      <button
                        onClick={() => doSell(pos.symbol)}
                        disabled={busy}
                        className="px-4 py-1.5 bg-red-800 hover:bg-red-700 text-white text-xs font-bold rounded disabled:opacity-40"
                      >
                        市價強制出場
                      </button>
                      <button
                        onClick={() => doCancelConditions(pos.symbol)}
                        disabled={busy}
                        className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs rounded disabled:opacity-40"
                      >
                        取消觸價單
                      </button>
                      <button
                        onClick={() => doDeleteRecord(pos.symbol)}
                        className="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-500 text-xs rounded"
                        title="觸價單已自行觸發，只刪記錄"
                      >
                        清除記錄
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* 說明 */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 text-xs text-gray-500 space-y-1.5">
          <div className="text-gray-400 font-semibold mb-2">觸價單說明</div>
          <div>• <span className="text-red-300">停損</span>：成交價跌到停損價時，系統自動送出<span className="text-orange-300">市價賣單（ROD）</span>。停損價 = 進場價 − N tick，向上捨入（更早觸發保護）</div>
          <div>• <span className="text-green-300">停利</span>：成交價漲到停利價時，系統自動送出<span className="text-orange-300">市價賣單（ROD）</span>。停利價 = 昨收 × (1 + 進場漲幅 + 附加%)，向下捨入</div>
          <div>• <span className="text-yellow-500">注意</span>：兩張觸價單同時存在，任一觸發後另一張<strong className="text-white">不會自動取消</strong>，需手動按「取消觸價單」</div>
          <div>• <span className="text-blue-300">市價強制買</span>：使用 IOC 市價單，無法成交的部分自動取消，適合急單</div>
          <div>• <span className="text-blue-300">市價強制出場</span>：送出 IOC 市價賣單並同時取消兩張觸價單</div>
        </div>
      </div>
    </div>
  )
}
