import { useEffect, useState } from 'react'
import axios from 'axios'
import { AreaChart, Area, ResponsiveContainer, Tooltip, ReferenceLine } from 'recharts'

interface PricePoint { date: string; close: number }

export function PriceSparkline({ code }: { code: string }) {
  const [data, setData] = useState<PricePoint[]>([])

  useEffect(() => {
    axios.get<PricePoint[]>(`/api/price/${code}`)
      .then(r => setData(r.data))
      .catch(() => {})
  }, [code])

  if (data.length < 5) return null

  const min = Math.min(...data.map(d => d.close))
  const max = Math.max(...data.map(d => d.close))
  const last = data[data.length - 1].close
  const first = data[0].close
  const isUp = last >= first
  const color = isUp ? '#22c55e' : '#ef4444'

  return (
    <div className="mt-3">
      <div className="flex justify-between text-[10px] text-gray-600 mb-0.5">
        <span>2M 走勢</span>
        <span className={isUp ? 'text-green-400' : 'text-red-400'}>
          {last.toFixed(1)} ({isUp ? '+' : ''}{((last - first) / first * 100).toFixed(1)}%)
        </span>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
          <defs>
            <linearGradient id={`grad-${code}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <ReferenceLine y={first} stroke="#4b5563" strokeDasharray="2 2" />
          <Area
            type="monotone"
            dataKey="close"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#grad-${code})`}
            dot={false}
            isAnimationActive={false}
          />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11, padding: '2px 6px' }}
            formatter={(v: number) => [v.toFixed(1), '']}
            labelFormatter={(l: string) => l.slice(5)}
          />
        </AreaChart>
      </ResponsiveContainer>
      <div className="flex justify-between text-[10px] text-gray-700">
        <span>{min.toFixed(0)}</span><span>{max.toFixed(0)}</span>
      </div>
    </div>
  )
}
