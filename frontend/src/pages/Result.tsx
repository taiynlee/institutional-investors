import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ResultData, ResultRow } from '../types'

function RowCard({ row }: { row: ResultRow }) {
  const up = row.chg_pct >= 0
  const dipStr = row.dip_bonus > 0 ? ` +${row.dip_bonus}資` : ''
  const holderVal = Math.round(row.holders_bonus)
  const holderStr = holderVal !== 0 ? ` ${holderVal > 0 ? '+' : ''}${holderVal}戶` : ''
  const streakStr = row.streak > 1 ? ` 連續${row.streak}日` : ''

  return (
    <div className="bg-gray-900 rounded-lg p-4">
      <div className="flex justify-between items-start">
        <div>
          <span className="text-white font-bold">{row.code} {row.name}</span>
          <span className="ml-2 text-gray-400 text-sm">
            昨[{row.tags || '?'}] 分={row.score}
            {dipStr}
            {holderStr}
            {streakStr}
          </span>
        </div>
        <span className={`text-lg font-bold ${up ? 'text-red-400' : 'text-green-400'}`}>
          {up ? '▲' : '▼'}{Math.abs(row.chg_pct)}%
        </span>
      </div>
      <div className="text-gray-500 text-sm mt-1">
        {row.prev_close} → {row.close}
      </div>
    </div>
  )
}

export function Result() {
  const [data, setData] = useState<ResultData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('/api/result')
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }, [])

  const avg = data?.rows.length
    ? (data.rows.reduce((s, r) => s + r.chg_pct, 0) / data.rows.length).toFixed(2)
    : null

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-3xl mx-auto">
        <div className="mb-6">
          <h2 className="text-xl font-black text-white">篩選績效</h2>
          {data?.pred_date && data?.price_date && (
            <p className="text-gray-400 text-sm">
              {data.pred_date} → {data.price_date}
              {avg !== null && (
                <span className={`ml-3 font-medium ${Number(avg) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                  均漲幅 {Number(avg) >= 0 ? '+' : ''}{avg}%
                </span>
              )}
            </p>
          )}
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : !data?.rows.length ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
        ) : (
          <div className="flex flex-col gap-3">
            {data.rows.map(row => <RowCard key={row.code} row={row} />)}
          </div>
        )}
      </div>
    </div>
  )
}
