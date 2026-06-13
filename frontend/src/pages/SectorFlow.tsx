import { useEffect, useState } from 'react'
import axios from 'axios'
import type { SectorFlow } from '../types'

interface SectorStock {
  code: string
  name: string
  net: number
}

function formatNet(n: number): string {
  const sign = n >= 0 ? '+' : ''
  if (Math.abs(n) >= 10000) return `${sign}${(n / 10000).toFixed(1)}萬張`
  if (Math.abs(n) >= 1000) return `${sign}${(n / 1000).toFixed(1)}K張`
  return `${sign}${n}張`
}

function SectorCard({
  sector,
  onSelect,
  selected,
}: {
  sector: SectorFlow
  onSelect: (s: string) => void
  selected: boolean
}) {
  const positive = sector.net >= 0
  const barWidth = Math.min(100, Math.abs(sector.net) / 500)
  return (
    <div
      className={`bg-gray-900 border rounded-lg p-3 cursor-pointer transition-colors ${
        selected ? 'border-blue-500' : 'border-gray-700 hover:border-gray-500'
      }`}
      onClick={() => onSelect(sector.sector)}
    >
      <div className="flex justify-between items-center mb-1">
        <span className="text-white text-sm font-medium">{sector.sector}</span>
        <span className={`text-sm font-bold ${positive ? 'text-red-400' : 'text-green-400'}`}>
          {formatNet(sector.net)}
        </span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${positive ? 'bg-red-500' : 'bg-green-500'}`}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      <div className="text-[10px] text-gray-600 mt-1">{sector.stock_count} 筆</div>
    </div>
  )
}

export function SectorFlow({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [sectors, setSectors] = useState<SectorFlow[]>([])
  const [stocks, setStocks] = useState<SectorStock[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [days, setDays] = useState(5)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get<SectorFlow[]>('/api/sector-flow', { params: { days } })
      .then(r => setSectors(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [days])

  useEffect(() => {
    if (!selected) return
    axios.get<SectorStock[]>(`/api/sector-stocks/${encodeURIComponent(selected)}`, { params: { days } })
      .then(r => setStocks(r.data))
      .catch(() => setStocks([]))
  }, [selected, days])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">類股資金流向</h1>
            <p className="text-gray-400 text-sm">法人近N日各類股買超合計（外資+投信）</p>
          </div>
          <div className="flex gap-2">
            {[3, 5, 10].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1 text-sm rounded ${
                  days === d ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}
              >
                {d}日
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : (
          <div className="flex gap-6">
            <div className="w-72 shrink-0">
              <div className="grid grid-cols-1 gap-2">
                {sectors.map(s => (
                  <SectorCard
                    key={s.sector}
                    sector={s}
                    onSelect={setSelected}
                    selected={selected === s.sector}
                  />
                ))}
              </div>
            </div>

            <div className="flex-1">
              {selected ? (
                <div>
                  <h3 className="text-lg font-bold text-white mb-4">{selected}</h3>
                  {stocks.length === 0 ? (
                    <div className="text-gray-500 text-sm">無資料</div>
                  ) : (
                    <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-800">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-gray-500 text-xs border-b border-gray-800">
                            <th className="px-4 py-3 text-left">代碼</th>
                            <th className="px-4 py-3 text-left">名稱</th>
                            <th className="px-4 py-3 text-right">法人淨額</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stocks.map(s => (
                            <tr key={s.code} className="border-b border-gray-800 hover:bg-gray-800">
                              <td
                                className="px-4 py-2.5 font-mono text-blue-300 cursor-pointer hover:text-blue-400"
                                onClick={() => onResearchStock?.(s.code)}
                              >{s.code}</td>
                              <td className="px-4 py-2.5 text-white">{s.name}</td>
                              <td className={`px-4 py-2.5 text-right font-bold ${s.net >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                                {formatNet(s.net)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-gray-600 text-sm">
                  點擊左側類股查看明細
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
