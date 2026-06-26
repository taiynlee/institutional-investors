import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

const API = '/fubon-api'

interface PoolStock { code: string; name: string }

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

export function ManualTradeContent() {
  const [pool, setPool] = useState<PoolStock[]>([])
  const [symbol, setSymbol] = useState('')
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  const [lots, setLots] = useState(1)
  const [stopTicks, setStopTicks] = useState(4)
  const [tpAddPct, setTpAddPct] = useState(4.0)
  const [busy, setBusy] = useState(false)
  const [fetchingPrice, setFetchingPrice] = useState(false)
  const [fetchingSellPrice, setFetchingSellPrice] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [showDropdown, setShowDropdown] = useState(false)
  const [sellSymbol, setSellSymbol] = useState('')
  const [sellName, setSellName] = useState('')
  const [sellPrice, setSellPrice] = useState('')
  const [sellLots, setSellLots] = useState(1)
  const [sellShowDropdown, setSellShowDropdown] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)
  const sellDropRef = useRef<HTMLDivElement>(null)

  const loadPool = () =>
    axios.get<PoolStock[]>('/api/pool').then(r => setPool(r.data)).catch(() => {})

  // 從交易設定載入停損/停利預設值
  const loadTradingParams = () =>
    axios.get(`${API}/trading-params`).then(r => {
      if (r.data.stop_loss_ticks != null) setStopTicks(r.data.stop_loss_ticks)
      if (r.data.take_profit_add_pct != null) setTpAddPct(r.data.take_profit_add_pct)
    }).catch(() => {})

  useEffect(() => {
    loadPool()
    loadTradingParams()
    const t = setInterval(loadTradingParams, 30_000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node))
        setShowDropdown(false)
      if (sellDropRef.current && !sellDropRef.current.contains(e.target as Node))
        setSellShowDropdown(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const filtered = pool.filter(s =>
    symbol.length >= 1 &&
    (s.code.includes(symbol) || s.name.includes(symbol))
  ).slice(0, 8)

  const entryPrice = parseFloat(price) || 0
  const ts = entryPrice > 0 ? tw_tick_size(entryPrice) : 0
  const stopLoss   = entryPrice > 0 ? round_up_tick(entryPrice - stopTicks * ts) : 0
  const takeProfit = entryPrice > 0 ? round_down_tick(entryPrice * (1 + tpAddPct / 100)) : 0

  const fetchPriceForCode = async (code: string) => {
    if (!code) return
    setFetchingPrice(true)
    try {
      const r = await axios.get(`${API}/manual-trade/price/${code}`)
      if (r.data.price > 0) setPrice(String(r.data.price))
      else setMsg({ ok: false, text: '引擎無此股報價，請手動輸入價格' })
    } catch {
      setMsg({ ok: false, text: '無法取得報價（引擎未啟動？）' })
    } finally {
      setFetchingPrice(false)
    }
  }

  const fetchSellPriceForCode = async (code: string) => {
    if (!code) return
    setFetchingSellPrice(true)
    try {
      const r = await axios.get(`${API}/manual-trade/price/${code}`)
      if (r.data.price > 0) setSellPrice(String(r.data.price))
      else setMsg({ ok: false, text: '引擎無此股報價，請手動輸入賣出價格' })
    } catch {
      setMsg({ ok: false, text: '無法取得報價（引擎未啟動？）' })
    } finally {
      setFetchingSellPrice(false)
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
          symbol, lots, price: entryPrice,
          prev_close: entryPrice,   // 無昨收，以買進價為停利基準
          stop_loss_ticks: stopTicks,
          take_profit_add_pct: tpAddPct,
          force_market: forceMarket,
        },
      })
      const note = r.data?.note ? ` ${r.data.note}` : ''
      setMsg({ ok: true, text: `✓ ${symbol} 買進 ${lots}張 @ ${entryPrice}，停損/停利觸價單已掛出${note}` })
      setSymbol(''); setName(''); setPrice('')
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally {
      setBusy(false)
    }
  }

  const doLimitSell = async () => {
    const sp = parseFloat(sellPrice)
    if (!sellSymbol || sp <= 0) {
      setMsg({ ok: false, text: '請選擇股票並輸入賣出價格' })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      await axios.post(`${API}/manual-trade/limit-sell`, null, {
        params: { symbol: sellSymbol, lots: sellLots, price: sp },
      })
      setMsg({ ok: true, text: `✓ ${sellSymbol} 限價賣出 ${sellLots}張 @ ${sp} 已送出` })
      setSellSymbol(''); setSellName(''); setSellPrice('')
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally {
      setBusy(false)
    }
  }

  const inp = 'bg-gray-800 border border-gray-700 text-white rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 w-full'
  const lbl = 'text-xs text-gray-500 mb-1 block'

  return (
    <div className="space-y-4">
      {/* 狀態訊息 */}
      {msg && (
        <div className={`text-sm px-4 py-3 rounded-lg ${msg.ok ? 'bg-green-900 text-green-300 border border-green-700' : 'bg-red-900 text-red-300 border border-red-700'}`}>
          {msg.text}
        </div>
      )}

      {/* 主體：左買 右賣 */}
      <div className="grid grid-cols-2 gap-4">

        {/* ── 左：買進 ── */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="text-sm font-bold text-white border-b border-gray-800 pb-2">
            買進
            <span className="text-xs text-gray-500 font-normal ml-2">真實下單 · 自動掛停損/停利觸價單</span>
          </div>

          {/* 股票 */}
          <div ref={dropRef}>
            <label className={lbl}>股票（pool 內）</label>
            <div className="relative">
              <input
                className={inp}
                value={symbol}
                onChange={e => { setSymbol(e.target.value); setShowDropdown(true) }}
                placeholder="代碼或名稱"
              />
              {showDropdown && filtered.length > 0 && (
                <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg overflow-hidden shadow-xl">
                  {filtered.map(s => (
                    <button
                      key={s.code}
                      onClick={() => {
                        setSymbol(s.code); setName(s.name); setShowDropdown(false)
                        setPrice('')
                        fetchPriceForCode(s.code)
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

          {/* 價格 */}
          <div>
            <label className={lbl}>買進價格（限價）</label>
            <div className="flex gap-2">
              <input className={inp} type="number" value={price}
                onChange={e => setPrice(e.target.value)} placeholder="例：250.5" step="0.01" />
              <button
                onClick={() => fetchPriceForCode(symbol)}
                disabled={fetchingPrice || !symbol}
                className="shrink-0 px-3 py-2 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded border border-gray-600 disabled:opacity-40"
              >
                {fetchingPrice ? '...' : '刷新'}
              </button>
            </div>
          </div>

          {/* 張數 */}
          <div>
            <label className={lbl}>張數</label>
            <input className={inp} type="number" value={lots}
              onChange={e => setLots(Math.max(1, parseInt(e.target.value) || 1))} min={1} />
          </div>

          {/* 停損 + 停利 */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>停損 tick 數</label>
              <input className={inp} type="number" value={stopTicks}
                onChange={e => setStopTicks(Math.max(1, parseInt(e.target.value) || 4))} min={1} />
            </div>
            <div>
              <label className={lbl}>停利附加漲幅 %</label>
              <input className={inp} type="number" value={tpAddPct}
                onChange={e => setTpAddPct(parseFloat(e.target.value) || 4)} step={0.5} min={0.5} />
            </div>
          </div>

          {/* 觸價單預覽 */}
          {entryPrice > 0 && (
            <div className="bg-gray-800 rounded-lg p-3 space-y-2 text-xs">
              <div className="text-gray-500 font-semibold uppercase tracking-wide text-[10px]">觸價單預覽</div>
              <div className="flex items-center gap-2">
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-900 text-red-300 border border-red-700">停損</span>
                <span className="text-red-300 font-mono font-bold">≤ {stopLoss.toFixed(2)}</span>
                <span className="text-gray-600">（進場 − {stopTicks} tick）</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-900 text-green-300 border border-green-700">停利</span>
                <span className="text-green-300 font-mono font-bold">≥ {takeProfit.toFixed(2)}</span>
                <span className="text-gray-600">（買進價 +{tpAddPct}%）</span>
              </div>
              <div className="text-gray-500 text-[10px] pt-1 border-t border-gray-700">
                兩單同時掛出，任一觸發後後端自動取消另一張
              </div>
            </div>
          )}

          {/* 下單按鈕 */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={() => doBuy(false)}
              disabled={busy || !symbol || entryPrice <= 0}
              className="flex-1 py-2.5 bg-red-700 hover:bg-red-600 text-white font-bold rounded-lg text-sm disabled:opacity-40"
            >
              {busy ? '下單中...' : `買進 ${lots}張`}
            </button>
            <button
              onClick={() => doBuy(true)}
              disabled={busy || !symbol}
              className="px-4 py-2.5 bg-orange-800 hover:bg-orange-700 text-white text-sm font-bold rounded-lg disabled:opacity-40"
              title="市價 IOC"
            >
              市價
            </button>
          </div>
        </div>

        {/* ── 右：賣出 ── */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="text-sm font-bold text-white border-b border-gray-800 pb-2">
            賣出
            <span className="text-xs text-gray-500 font-normal ml-2">限價現賣 ROD</span>
          </div>

          {/* 股票 */}
          <div ref={sellDropRef}>
            <label className={lbl}>股票（pool 內）</label>
            <div className="relative">
              <input
                className={inp}
                value={sellSymbol}
                onChange={e => { setSellSymbol(e.target.value); setSellShowDropdown(true) }}
                placeholder="代碼或名稱"
              />
              {(() => {
                const sellFiltered = pool.filter(s =>
                  sellSymbol.length >= 1 &&
                  (s.code.includes(sellSymbol) || s.name.includes(sellSymbol))
                ).slice(0, 8)
                return sellShowDropdown && sellFiltered.length > 0 ? (
                  <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg overflow-hidden shadow-xl">
                    {sellFiltered.map(s => (
                      <button
                        key={s.code}
                        onClick={() => {
                          setSellSymbol(s.code); setSellName(s.name); setSellShowDropdown(false)
                          setSellPrice('')
                          fetchSellPriceForCode(s.code)
                        }}
                        className="w-full text-left px-4 py-2 hover:bg-gray-700 flex gap-3 items-center"
                      >
                        <span className="font-mono text-blue-300 w-14">{s.code}</span>
                        <span className="text-gray-300">{s.name}</span>
                      </button>
                    ))}
                  </div>
                ) : null
              })()}
            </div>
            {sellName && <div className="text-xs text-gray-500 mt-1">{sellName}</div>}
          </div>

          {/* 賣出價格 */}
          <div>
            <label className={lbl}>賣出價格（限價）</label>
            <div className="flex gap-2">
              <input className={inp} type="number" value={sellPrice}
                onChange={e => setSellPrice(e.target.value)} placeholder="例：250.5" step="0.01" />
              <button
                onClick={() => fetchSellPriceForCode(sellSymbol)}
                disabled={fetchingSellPrice || !sellSymbol}
                className="shrink-0 px-3 py-2 text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 rounded border border-gray-600 disabled:opacity-40"
              >
                {fetchingSellPrice ? '...' : '刷新'}
              </button>
            </div>
          </div>

          {/* 張數 */}
          <div>
            <label className={lbl}>張數</label>
            <input className={inp} type="number" value={sellLots}
              onChange={e => setSellLots(Math.max(1, parseInt(e.target.value) || 1))} min={1} />
          </div>

          {/* 下單 */}
          <button
            onClick={doLimitSell}
            disabled={busy || !sellSymbol || parseFloat(sellPrice) <= 0}
            className="w-full py-2.5 bg-green-800 hover:bg-green-700 text-white font-bold rounded-lg text-sm disabled:opacity-40 mt-2"
          >
            {busy ? '下單中...' : `賣出 ${sellLots}張`}
          </button>
        </div>
      </div>

      {/* 說明（折疊式，預設收起） */}
      <details className="bg-gray-900 rounded-xl border border-gray-800 p-4">
        <summary className="text-xs text-gray-500 cursor-pointer select-none">觸價單說明 ▸</summary>
        <div className="mt-3 space-y-1.5 text-xs text-gray-500">
          <div>• <span className="text-red-300">停損</span>：成交價 ≤ 停損價時送出市價賣單（ROD）。停損價 = 進場價 − N tick，向上捨入</div>
          <div>• <span className="text-green-300">停利</span>：成交價 ≥ 停利價時送出市價賣單（ROD）。停利價 = 買進價 × (1 + 附加%)，向下捨入</div>
          <div>• <span className="text-blue-400">OCO</span>：後端已掛 <code>set_on_order_changed</code> callback，任一觸發後自動取消另一張</div>
          <div>• <span className="text-orange-300">市價買進</span>：使用 IOC 市價單強制成交，同時掛停損/停利觸價單</div>
          <div>• <span className="text-green-300">限價賣出</span>：ROD 限價現賣，與買進持倉記錄無關，不影響觸價單</div>
        </div>
      </details>
    </div>
  )
}

export function ManualTradePage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto">
        <div className="mb-4">
          <h1 className="text-2xl font-black text-white">手動買賣</h1>
          <p className="text-gray-500 text-sm mt-1">真實下單 · 與 dry_run 無關</p>
        </div>
        <ManualTradeContent />
      </div>
    </div>
  )
}
