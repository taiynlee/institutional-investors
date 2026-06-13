import { useEffect, useState } from 'react'
import axios from 'axios'
import { useServerClock } from '../hooks/useServerTime'

interface MarketIndex {
  symbol: string
  name: string
  close: number
  chg_pts: number
  chg_pct: number
}

interface TaifexFutures {
  diff: number
  diff_pct: number | null
  last: number
  date: string
  time: string
}

export function MarketHeader() {
  const [indices, setIndices] = useState<MarketIndex[]>([])
  const [futures, setFutures] = useState<TaifexFutures | null>(null)
  const clock = useServerClock()

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

  if (indices.length === 0 && !clock) return null

  return (
    <div className="bg-gray-900 border-b border-gray-800 px-4 py-1">
      {/* Row 1: market indices + futures — wrap instead of scroll */}
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 items-center">
        {indices.map(idx => (
          <div key={idx.symbol} className="flex items-center gap-1.5 shrink-0">
            <span className="text-gray-400 text-[11px]">{idx.name}</span>
            <span className="text-white text-[11px] font-bold">{idx.close.toLocaleString()}</span>
            <span className={`text-[11px] font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idx.chg_pts >= 0 ? '+' : ''}{idx.chg_pts.toLocaleString()}
            </span>
            <span className={`text-[11px] font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idx.chg_pct >= 0 ? '+' : ''}{idx.chg_pct.toFixed(2)}%
            </span>
          </div>
        ))}
        {futures && (
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-gray-400 text-[11px]">台指期</span>
            <span className={`text-[11px] font-bold font-mono ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {futures.diff >= 0 ? '+' : ''}{futures.diff.toFixed(0)}
            </span>
            {futures.diff_pct != null && (
              <span className={`text-[11px] ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                ({futures.diff >= 0 ? '+' : ''}{futures.diff_pct.toFixed(2)}%)
              </span>
            )}
          </div>
        )}
      </div>
      {/* Row 2: clock right-aligned */}
      {clock && (
        <div className="flex justify-end -mt-0.5">
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-gray-700 bg-gray-800">
            <span className="text-gray-500 text-[10px]">台灣</span>
            <span className="text-gray-400 text-[10px]">{clock.date}</span>
            <span className="text-white text-[11px] font-mono font-bold tabular-nums">{clock.time}</span>
          </div>
        </div>
      )}
    </div>
  )
}
