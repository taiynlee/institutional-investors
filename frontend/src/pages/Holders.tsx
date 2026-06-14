import { useEffect, useState } from 'react'

interface HolderRow {
  code: string
  name: string
  sector: string
  report_date: string
  holders: number
  pct: number
  prev_holders: number | null
  prev_pct: number | null
  holders_chg: number | null
  pct_chg: number | null
}

function ChgBadge({ v, suffix = '' }: { v: number | null; suffix?: string }) {
  if (v === null) return <span className="text-gray-600">—</span>
  if (v > 0) return <span className="text-green-400">+{v}{suffix}</span>
  if (v < 0) return <span className="text-red-400">{v}{suffix}</span>
  return <span className="text-gray-500">0{suffix}</span>
}

export function Holders({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [rows, setRows] = useState<HolderRow[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch('/api/holders')
      .then(r => r.json())
      .then(data => { setRows(data); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  const filtered = search
    ? rows.filter(r => r.code.includes(search) || r.name.includes(search) || r.sector.includes(search))
    : rows

  const reportDate = rows[0]?.report_date ?? ''

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">千張大戶占比排行</h1>
            <p className="text-gray-400 text-sm">資料日期：{reportDate}，千張以上法人占流通股本比例</p>
          </div>
          <input
            type="text"
            placeholder="搜尋代碼/名稱/類股"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-1.5 w-48 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div className="mb-4 flex gap-2 items-center">
          <span className="text-xs text-gray-500 bg-gray-800 px-3 py-1.5 rounded-lg">依週增減% 排序</span>
          <span className="ml-auto text-xs text-gray-500">{filtered.length} 檔</span>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : (
          <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left w-6">#</th>
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-left">類股</th>
                  <th className="px-4 py-3 text-right">千張人數</th>
                  <th className="px-4 py-3 text-right">週增減</th>
                  <th className="px-4 py-3 text-right">占比%</th>
                  <th className="px-4 py-3 text-right">週增減%</th>
                  <th className="px-4 py-3 text-right text-gray-600">上週占比</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={r.code} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                    <td className="px-4 py-2.5 text-gray-600 text-xs">{i + 1}</td>
                    <td
                      className="px-4 py-2.5 font-mono text-blue-300 cursor-pointer hover:text-blue-400"
                      onClick={() => onResearchStock?.(r.code)}
                    >{r.code}</td>
                    <td className="px-4 py-2.5 font-medium text-white">{r.name}</td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">{r.sector}</td>
                    <td className="px-4 py-2.5 text-right text-white font-bold">{r.holders}</td>
                    <td className="px-4 py-2.5 text-right font-medium">
                      <ChgBadge v={r.holders_chg} />
                    </td>
                    <td className="px-4 py-2.5 text-right text-white font-bold">{r.pct.toFixed(2)}%</td>
                    <td className="px-4 py-2.5 text-right font-medium">
                      <ChgBadge v={r.pct_chg} suffix="%" />
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-600 text-xs">
                      {r.prev_pct !== null ? `${r.prev_pct.toFixed(2)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
