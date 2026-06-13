import { useEffect, useState } from 'react'
import axios from 'axios'
import type { WatchlistAItem } from '../types'

export function WatchlistAPage({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [items, setItems] = useState<WatchlistAItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get<WatchlistAItem[]>('/api/watchlist-a')
      .then(r => setItems(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">策略A 追蹤清單</h1>
          <p className="text-gray-400 text-sm">曾出現策略A訊號，等待BB拉回≤5的進場時機</p>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : items.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
        ) : (
          <div className="bg-gray-900 rounded-xl overflow-x-auto border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-left">加入日</th>
                  <th className="px-4 py-3 text-right">加入收盤</th>
                  <th className="px-4 py-3 text-right">加入BB</th>
                  <th className="px-4 py-3 text-right">A分</th>
                  <th className="px-4 py-3 text-right">到位日</th>
                  <th className="px-4 py-3 text-right">到位收盤</th>
                  <th className="px-4 py-3 text-right">現價</th>
                </tr>
              </thead>
              <tbody>
                {items.map(item => {
                  const chgColor = item.chg_pct === null ? '' : item.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'
                  return (
                    <tr key={item.id} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                      <td
                        className="px-4 py-3 font-mono text-blue-300 font-bold cursor-pointer hover:text-blue-400"
                        onClick={() => onResearchStock?.(item.code)}
                      >{item.code}</td>
                      <td className="px-4 py-3 text-white">{item.name}</td>
                      <td className="px-4 py-3 text-gray-400 text-sm">{item.added_date}</td>
                      <td className="px-4 py-3 text-right text-gray-300">{item.added_close}</td>
                      <td className="px-4 py-3 text-right text-gray-300">
                        {item.added_bb_position.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 text-right text-blue-300 font-bold">
                        {item.added_score_a.toFixed(0)}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-400 text-sm">
                        {item.triggered_date ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {item.triggered_close ? (
                          <span className="text-green-400">{item.triggered_close}</span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {item.current_close ? (
                          <span className={chgColor}>
                            {item.current_close}
                            {item.chg_pct !== null && (
                              <span className="text-xs ml-1">({item.chg_pct >= 0 ? '+' : ''}{item.chg_pct?.toFixed(2)}%)</span>
                            )}
                          </span>
                        ) : '—'}
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
