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

function ChgBadge({ val }: { val: number | null }) {
  if (val === null) return <span className="text-gray-600">—</span>
  const color = val > 0 ? 'text-red-400' : val < 0 ? 'text-green-400' : 'text-gray-400'
  return <span className={`font-mono ${color}`}>{val > 0 ? '+' : ''}{val.toFixed(2)}%</span>
}

export function UsStocksPage() {
  const [stocks, setStocks] = useState<UsStock[]>([])
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    // only fetch on Taiwan trading days
    try {
      const r = await axios.get<{ trading: boolean }>('/api/is-trading-day')
      if (!r.data.trading) return
    } catch { /* if check fails, still fetch */ }
    load()
  }

  useEffect(() => {
    load()
    // schedule next fetch at 08:55 Taiwan time daily
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

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-end mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">美股追蹤</h1>
            <p className="text-gray-400 text-sm">收盤價 ＋ 盤後價　每日 08:55 自動更新</p>
          </div>
          <div className="flex items-center gap-3">
            {updatedAt && <span className="text-xs text-gray-500">更新 {updatedAt}</span>}
            <button
              onClick={load}
              className="text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700"
            >
              重新整理
            </button>
          </div>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">抓取中（約 10–20 秒）...</div>
        ) : stocks.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
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
                  <th className="px-4 py-3 text-right">盤後-收盤</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map(s => {
                  const highlight = s.chg_pct > 0 && s.post_chg_pct != null && s.post_chg_pct > 3
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
                    <td className="px-4 py-3 text-right font-mono">
                      {s.post_price != null ? (() => {
                        const diff = s.post_price - s.close
                        const color = diff > 0 ? 'text-red-400' : diff < 0 ? 'text-green-400' : 'text-gray-400'
                        return <span className={color}>{diff > 0 ? '+' : ''}{diff.toFixed(2)}</span>
                      })() : <span className="text-gray-600">—</span>}
                    </td>
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
