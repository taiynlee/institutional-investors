import { useEffect, useState } from 'react'
import axios from 'axios'

interface FlowItem { code: string; name: string; net: number }
interface FlowData { buy: FlowItem[]; sell: FlowItem[] }

function formatNet(n: number) {
  const sign = n >= 0 ? '+' : ''
  if (Math.abs(n) >= 10000) return `${sign}${(n / 10000).toFixed(1)}萬`
  if (Math.abs(n) >= 1000) return `${sign}${(n / 1000).toFixed(1)}K`
  return `${sign}${n}`
}

export function InstFlowTable({ days = 5 }: { days?: number }) {
  const [data, setData] = useState<FlowData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get<FlowData>('/api/inst-flow', { params: { days } })
      .then(r => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [days])

  if (loading) return <div className="text-gray-500 text-sm py-4 text-center">載入中...</div>
  if (!data) return null

  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="text-sm font-bold text-red-400 mb-2">買超排行</h3>
        <div className="space-y-1">
          {data.buy.slice(0, 20).map((item, i) => (
            <div key={item.code} className="flex items-center gap-2 text-xs">
              <span className="text-gray-600 w-4">{i + 1}</span>
              <span className="font-mono text-blue-300 w-10">{item.code}</span>
              <span className="text-gray-300 flex-1 truncate">{item.name}</span>
              <span className="text-red-400 font-bold">{formatNet(item.net)}</span>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3 className="text-sm font-bold text-green-400 mb-2">賣超排行</h3>
        <div className="space-y-1">
          {data.sell.slice(0, 20).map((item, i) => (
            <div key={item.code} className="flex items-center gap-2 text-xs">
              <span className="text-gray-600 w-4">{i + 1}</span>
              <span className="font-mono text-blue-300 w-10">{item.code}</span>
              <span className="text-gray-300 flex-1 truncate">{item.name}</span>
              <span className="text-green-400 font-bold">{formatNet(item.net)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
