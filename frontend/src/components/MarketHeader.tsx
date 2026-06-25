import { useEffect, useState } from 'react'
import axios from 'axios'

interface MarketIndex {
  symbol: string
  name: string
  close: number
  chg_pts: number
  chg_pct: number
  date?: string
}

interface TaifexFutures {
  session: 'night' | 'day'
  diff: number
  diff_pct: number | null
  last: number
  date: string
  time: string
}

export function MarketHeader() {
  const [indices, setIndices] = useState<MarketIndex[]>([])
  const [futures, setFutures] = useState<TaifexFutures | null>(null)

  useEffect(() => {
    const loadIndices = () => {
      axios.get<MarketIndex[]>('/api/market-overview')
        .then(r => setIndices(r.data))
        .catch(() => {})
    }
    const loadFutures = () => {
      axios.get<TaifexFutures | null>('/api/taifex-futures')
        .then(r => setFutures(r.data))
        .catch(() => {})
    }
    loadIndices()
    loadFutures()
    const t1 = setInterval(loadIndices, 5 * 60 * 1000)
    const t2 = setInterval(loadFutures, 5 * 60 * 1000)
    return () => { clearInterval(t1); clearInterval(t2) }
  }, [])

  if (indices.length === 0) return null

  return (
    <div className="bg-gray-900 border-b border-gray-800 px-4 py-1">
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 items-center">
        {indices.map(idx => (
          <div key={idx.symbol} className="flex items-center gap-1.5 shrink-0">
            <span className="text-gray-400 text-xs">{idx.name}</span>
            {idx.date && <span className="text-gray-600 text-[10px]">{idx.date}</span>}
            <span className="text-white text-xs font-bold">{idx.close.toLocaleString()}</span>
            <span className={`text-xs font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idx.chg_pts >= 0 ? '+' : ''}{idx.chg_pts.toLocaleString()}
            </span>
            <span className={`text-xs font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idx.chg_pct >= 0 ? '+' : ''}{idx.chg_pct.toFixed(2)}%
            </span>
          </div>
        ))}
        {futures && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-gray-400 text-xs">{futures.session === 'night' ? '台指夜' : '台指期'}</span>
            <span className={`text-xs font-medium ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {futures.diff >= 0 ? '+' : ''}{futures.diff.toFixed(0)}
            </span>
            {futures.diff_pct != null && (
              <span className={`text-xs font-medium ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                {futures.diff >= 0 ? '+' : ''}{futures.diff_pct.toFixed(2)}%
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
