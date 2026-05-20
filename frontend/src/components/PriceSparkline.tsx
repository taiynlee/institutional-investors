import { useEffect, useState } from 'react'
import axios from 'axios'

interface PricePoint { date: string; close: number }

export function PriceSparkline({ code }: { code: string }) {
  const [data, setData] = useState<PricePoint[]>([])

  useEffect(() => {
    axios.get<PricePoint[]>(`/api/price/${code}`)
      .then(r => setData(r.data))
      .catch(() => {})
  }, [code])

  if (data.length < 5) return null

  const closes = data.map(d => d.close)
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const range = max - min || 1
  const first = closes[0]
  const last = closes[closes.length - 1]
  const isUp = last >= first
  const color = isUp ? '#22c55e' : '#ef4444'
  const pct = ((last - first) / first * 100).toFixed(1)

  const W = 280
  const H = 56
  const points = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * W
    const y = H - ((c - min) / range) * H
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')

  const baseY = (H - ((first - min) / range) * H).toFixed(1)

  return (
    <div className="mt-3">
      <div className="flex justify-between text-[10px] text-gray-600 mb-0.5">
        <span>2M 走勢</span>
        <span style={{ color }}>{last.toFixed(1)} ({isUp ? '+' : ''}{pct}%)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
        <line x1="0" y1={baseY} x2={W} y2={baseY} stroke="#374151" strokeWidth="1" strokeDasharray="3 3" />
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <div className="flex justify-between text-[10px] text-gray-700 mt-0.5">
        <span>{data[0].date.slice(5)}</span>
        <span>{data[data.length - 1].date.slice(5)}</span>
      </div>
    </div>
  )
}
