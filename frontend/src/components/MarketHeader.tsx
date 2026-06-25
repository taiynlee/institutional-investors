import { useEffect, useLayoutEffect, useState, useRef } from 'react'
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
  const rowRef = useRef<HTMLDivElement>(null)

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

  // 自動縮字：確保內容永遠在單行呈現（paint 前執行避免閃爍）
  useLayoutEffect(() => {
    const fit = () => {
      const el = rowRef.current
      if (!el) return
      const availWidth = el.parentElement?.clientWidth ?? window.innerWidth
      let size = 12
      el.style.fontSize = `${size}px`
      // scrollWidth vs 父容器寬：flex 容器本身會隨內容撐開，不能比自己
      while (el.scrollWidth > availWidth && size > 6.5) {
        size -= 0.25
        el.style.fontSize = `${size}px`
      }
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  }, [indices, futures])

  if (indices.length === 0) return null

  return (
    <div className="bg-gray-900 border-b border-gray-800 px-4 py-1 overflow-hidden">
      <div ref={rowRef} className="flex gap-x-4 items-center whitespace-nowrap">
        {indices.map(idx => (
          <div key={idx.symbol} className="flex items-center gap-1 shrink-0">
            <span className="text-gray-400">{idx.name}</span>
            {idx.date && <span className="text-gray-600 opacity-80">{idx.date}</span>}
            <span className="text-white font-bold">{idx.close.toLocaleString()}</span>
            <span className={`font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idx.chg_pts >= 0 ? '+' : ''}{idx.chg_pts.toLocaleString()}
            </span>
            <span className={`font-medium ${idx.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              ({idx.chg_pct >= 0 ? '+' : ''}{idx.chg_pct.toFixed(2)}%)
            </span>
          </div>
        ))}
        {futures && (
          <div className="flex items-center gap-1 shrink-0">
            <span className="text-gray-400">{futures.session === 'night' ? '台指夜' : '台指期'}</span>
            <span className={`font-medium ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {futures.diff >= 0 ? '+' : ''}{futures.diff.toFixed(0)}
            </span>
            {futures.diff_pct != null && (
              <span className={`font-medium ${futures.diff >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                ({futures.diff >= 0 ? '+' : ''}{futures.diff_pct.toFixed(2)}%)
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
