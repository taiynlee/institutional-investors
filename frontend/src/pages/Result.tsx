import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ResultData, ResultRow } from '../types'

function RowCard({ row }: { row: ResultRow }) {
  const up = row.chg_pct >= 0
  const dot = row.score >= 80 ? 'text-green-400' : row.score >= 60 ? 'text-yellow-400' : 'text-red-400'
  const dipStr = row.dip_bonus > 0 ? ` +${row.dip_bonus}資` : ''
  const holderVal = Math.round(row.holders_bonus)
  const holderStr = holderVal !== 0 ? ` ${holderVal > 0 ? '+' : ''}${holderVal}戶` : ''
  const streakStr = row.streak > 1 ? `連續${row.streak}日` : `初次`

  return (
    <div className="bg-gray-900 rounded-lg p-4 flex gap-2 items-start">
      <span className={`text-lg leading-none mt-0.5 ${dot}`}>●</span>
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start">
          <div className="text-white text-sm font-bold">
            {row.code} {row.name}{' '}
            <span className="text-gray-400 font-normal">
              [{row.tags || '?'}] 分={row.score}{dipStr}{holderStr}
            </span>
          </div>
          <span className={`text-sm font-bold ml-3 shrink-0 ${up ? 'text-red-400' : 'text-green-400'}`}>
            {up ? '▲' : '▼'}{Math.abs(row.chg_pct)}%
          </span>
        </div>
        <div className="text-gray-500 text-xs mt-0.5 flex gap-3">
          <span>{streakStr}</span>
          <span>BB={row.bb_position.toFixed(1)}</span>
          <span>chip6d={row.chip_ratio_6d.toFixed(2)}%</span>
          <span className="text-gray-600">{row.prev_close}→{row.close}</span>
        </div>
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
