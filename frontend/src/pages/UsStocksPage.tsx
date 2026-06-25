import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { msUntilNextTaiwanTime } from '../hooks/useServerTime'

interface UsStock {
  symbol: string
  name: string
  close: number
  chg_pct: number
  post_price: number | null
  post_chg_pct: number | null
}

interface WatchItem {
  id: number
  symbol: string
  name: string
}

const KNOWN_NAMES: Record<string, string> = {
  TSM: '台積電ADR', NVDA: '輝達', MU: '美光', WDC: '威騰', TSLA: '特斯拉',
  GOOGL: 'Alphabet', MSFT: '微軟', AMZN: '亞馬遜', AAPL: '蘋果',
  MRVL: 'Marvell', LITE: 'Lumentum', AAOI: 'AAOI', SPCX: 'SpaceX',
  SNDK: '晟碟', INTC: '英特爾', AMD: 'AMD', QCOM: '高通', AVGO: '博通',
  AMAT: '應用材料', KLAC: 'KLA', LRCX: 'Lam Research', ASML: 'ASML',
  ARM: 'Arm', SMCI: '超微電腦', ON: '安森美', WOLF: 'Wolfspeed',
  NFLX: 'Netflix', META: 'Meta', AMKR: '艾克爾', ONTO: 'Onto Innovation',
}

function ChgBadge({ val }: { val: number | null }) {
  if (val === null) return <span className="text-gray-600">—</span>
  const color = val > 0 ? 'text-red-400' : val < 0 ? 'text-green-400' : 'text-gray-400'
  return <span className={`font-mono ${color}`}>{val > 0 ? '+' : ''}{val.toFixed(2)}%</span>
}

export function UsStocksPage() {
  const [stocks, setStocks] = useState<UsStock[]>([])
  const [watchlist, setWatchlist] = useState<WatchItem[]>([])
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [showManage, setShowManage] = useState(false)
  const [addSymbol, setAddSymbol] = useState('')
  const [addName, setAddName] = useState('')
  const [addError, setAddError] = useState('')
  const [adding, setAdding] = useState(false)
  const [lookingUp, setLookingUp] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadWatchlist = () => {
    axios.get<WatchItem[]>('/api/us-watchlist').then(r => setWatchlist(r.data)).catch(() => {})
  }

  const load = () => {
    setLoading(true)
    axios.get<UsStock[]>('/api/us-stocks')
      .then(r => {
        setStocks(r.data)
        setUpdatedAt(new Date().toLocaleTimeString('zh-TW', { timeZone: 'Asia/Taipei', hour: '2-digit', minute: '2-digit' }))
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  const scheduledLoad = async () => {
    try {
      const r = await axios.get<{ trading: boolean }>('/api/is-trading-day')
      if (!r.data.trading) return
    } catch { /* if check fails, still fetch */ }
    load()
  }

  useEffect(() => {
    load()
    loadWatchlist()
    const scheduleNext = () => {
      const ms = msUntilNextTaiwanTime(8, 55)
      timerRef.current = setTimeout(() => {
        scheduledLoad()
        setInterval(scheduledLoad, 24 * 60 * 60 * 1000)
      }, ms)
    }
    scheduleNext()
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [])

  const KNOWN_NAMES_REV = Object.fromEntries(Object.entries(KNOWN_NAMES).map(([k, v]) => [v, k]))

  const handleNameBlur = () => {
    const name = addName.trim()
    if (!name || addSymbol) return
    const sym = KNOWN_NAMES_REV[name]
    if (sym) setAddSymbol(sym)
  }

  const handleSymbolBlur = async () => {
    const sym = addSymbol.trim().toUpperCase()
    if (!sym || addName) return
    // 1. 先查靜態中文 map
    if (KNOWN_NAMES[sym]) { setAddName(KNOWN_NAMES[sym]); return }
    // 2. fallback：yfinance 英文名
    setLookingUp(true)
    try {
      const r = await axios.get<{ symbol: string; eng_name: string }>(`/api/us-stock-lookup?symbol=${sym}`)
      if (r.data.eng_name) setAddName(r.data.eng_name)
    } catch { /* ignore */ } finally {
      setLookingUp(false)
    }
  }

  const handleAdd = async () => {
    const sym = addSymbol.trim().toUpperCase()
    if (!sym) { setAddError('請輸入代號'); return }
    setAdding(true)
    setAddError('')
    try {
      await axios.post('/api/us-watchlist', { symbol: sym, name: addName.trim() })
      setAddSymbol('')
      setAddName('')
      loadWatchlist()
      load()
    } catch (e: any) {
      setAddError(e.response?.data?.detail ?? '新增失敗')
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (symbol: string) => {
    try {
      await axios.delete(`/api/us-watchlist/${symbol}`)
      loadWatchlist()
      setStocks(prev => prev.filter(s => s.symbol !== symbol))
    } catch {}
  }

  // Merge watchlist order with price data
  const stockMap = Object.fromEntries(stocks.map(s => [s.symbol, s]))

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-end mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">美股追蹤</h1>
            <p className="text-gray-400 text-sm">收盤價 ＋ 盤後價　每日 08:55 自動更新</p>
          </div>
          <div className="flex items-center gap-3">
            {updatedAt && <span className="text-xs text-gray-500">更新 {updatedAt}</span>}
            <button
              onClick={() => setShowManage(v => !v)}
              className={`text-xs px-3 py-1.5 rounded border transition-colors ${
                showManage
                  ? 'bg-blue-900 border-blue-600 text-blue-200'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700'
              }`}
            >
              {showManage ? '✕ 關閉管理' : '✏ 管理清單'}
            </button>
            <button
              onClick={load}
              className="text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700"
            >
              重新整理
            </button>
          </div>
        </div>

        {/* Management panel */}
        {showManage && (
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 mb-5 space-y-4">
            <div className="text-sm font-semibold text-gray-300 mb-3">管理美股追蹤清單</div>

            {/* Add form */}
            <div className="flex gap-2 items-end flex-wrap">
              <div>
                <label className="text-xs text-gray-500 block mb-1">代號（必填）</label>
                <input
                  type="text"
                  value={addSymbol}
                  onChange={e => { setAddSymbol(e.target.value.toUpperCase()); setAddName('') }}
                  onBlur={handleSymbolBlur}
                  onKeyDown={e => e.key === 'Enter' && handleAdd()}
                  placeholder="NVDA"
                  className="bg-gray-800 border border-gray-700 text-white rounded px-3 py-1.5 text-sm w-28 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  名稱　{lookingUp && <span className="text-gray-600">查詢中...</span>}
                </label>
                <input
                  type="text"
                  value={addName}
                  onChange={e => setAddName(e.target.value)}
                  onBlur={handleNameBlur}
                  onKeyDown={e => e.key === 'Enter' && handleAdd()}
                  placeholder="輝達（可改為中文）"
                  className="bg-gray-800 border border-gray-700 text-white rounded px-3 py-1.5 text-sm w-44 focus:outline-none focus:border-blue-500"
                />
              </div>
              <button
                onClick={handleAdd}
                disabled={adding}
                className="px-4 py-1.5 bg-blue-700 hover:bg-blue-600 text-white text-sm rounded disabled:opacity-50"
              >
                {adding ? '加入中...' : '+ 加入'}
              </button>
            </div>
            {addError && <div className="text-red-400 text-xs">{addError}</div>}

            {/* Current watchlist */}
            <div className="border-t border-gray-800 pt-3">
              <div className="text-xs text-gray-500 mb-2">目前清單（{watchlist.length} 檔）</div>
              <div className="flex flex-wrap gap-2">
                {watchlist.map(w => (
                  <div key={w.symbol} className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1">
                    <span className="text-blue-300 font-mono text-sm font-bold">{w.symbol}</span>
                    {w.name && <span className="text-gray-400 text-xs">{w.name}</span>}
                    <button
                      onClick={() => handleDelete(w.symbol)}
                      className="text-gray-600 hover:text-red-400 text-xs ml-1 transition-colors"
                      title="移除"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-center text-gray-500 py-20">抓取中（約 10–20 秒）...</div>
        ) : stocks.length === 0 && watchlist.length === 0 ? (
          <div className="text-center text-gray-500 py-20">清單為空，請點「管理清單」新增</div>
        ) : stocks.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無價格資料，請點「重新整理」</div>
        ) : (
          <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">代號</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-right">收盤價</th>
                  <th className="px-4 py-3 text-right">收盤漲跌</th>
                  <th className="px-4 py-3 text-right">盤後價</th>
                  <th className="px-4 py-3 text-right">盤後漲跌</th>
                  {showManage && <th className="px-4 py-3 w-8"></th>}
                </tr>
              </thead>
              <tbody>
                {stocks.map(s => {
                  const highlight = s.chg_pct >= 0 && s.post_chg_pct != null && s.post_chg_pct > 3
                  return (
                    <tr key={s.symbol} className={`border-b border-gray-800 transition-colors ${highlight ? 'bg-amber-950 hover:bg-amber-900' : 'hover:bg-gray-800'}`}>
                      <td className="px-4 py-3 font-mono text-blue-300 font-bold">{s.symbol}</td>
                      <td className="px-4 py-3 text-gray-300">{s.name}</td>
                      <td className="px-4 py-3 text-right text-white font-mono">{s.close.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right"><ChgBadge val={s.chg_pct} /></td>
                      <td className="px-4 py-3 text-right font-mono text-gray-300">
                        {s.post_price != null ? s.post_price.toFixed(2) : <span className="text-gray-600">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right"><ChgBadge val={s.post_chg_pct} /></td>
                      {showManage && (
                        <td className="px-4 py-3 text-center">
                          <button
                            onClick={() => handleDelete(s.symbol)}
                            className="text-gray-600 hover:text-red-400 text-xs transition-colors"
                            title="移除"
                          >
                            ✕
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
