import { useEffect, useState } from 'react'
import axios from 'axios'

interface Peer { code: string; name: string; close: number | null }

export function StockPeers({ code }: { code: string }) {
  const [peers, setPeers] = useState<Peer[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get<Peer[]>(`/api/stock-peers/${code}`)
      .then(r => setPeers(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [code])

  if (loading) return <div className="text-gray-500 text-xs">載入中...</div>
  if (peers.length === 0) return <div className="text-gray-600 text-xs">無同業資料</div>

  return (
    <div className="flex flex-wrap gap-2">
      {peers.map(p => (
        <div key={p.code} className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-xs">
          <span className="font-mono text-blue-300">{p.code}</span>
          <span className="text-gray-400 ml-1">{p.name}</span>
          {p.close !== null && (
            <span className="text-white ml-1 font-bold">{p.close}</span>
          )}
        </div>
      ))}
    </div>
  )
}
