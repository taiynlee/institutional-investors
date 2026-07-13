import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ResultData, ResultDateItem, ResultRow } from '../types'

type TagFilter = 'all' | 'A' | 'B'

function rowBg(row: ResultRow): string {
  if (row.is_ai_pick && row.is_top_score) return 'bg-purple-950 border border-purple-600'
  if (row.is_ai_pick) return 'bg-blue-950 border border-blue-700'
  if (row.is_top_score) return 'bg-yellow-950 border border-yellow-700'
  return 'bg-gray-900'
}

function RowCard({ row, onResearchStock }: { row: ResultRow; onResearchStock?: (code: string) => void }) {
  const up = row.chg_pct >= 0
  const dot = row.score_b >= 80 ? 'text-green-400' : row.score_b >= 60 ? 'text-yellow-400' : 'text-red-400'
  const dipStr = row.dip_bonus > 0 ? ` +${row.dip_bonus}資` : ''
  const holderStr = row.holders_bonus !== 0 ? ` ${row.holders_bonus > 0 ? '+' : ''}${row.holders_bonus.toFixed(2)}%戶` : ''
  const streakStr = row.streak > 1 ? `連續${row.streak}日` : `初次`
  const badge = row.is_ai_pick && row.is_top_score
    ? <span className="text-[10px] bg-purple-800 text-purple-200 px-1.5 py-0.5 rounded mr-1">AI精選+第一</span>
    : row.is_ai_pick
    ? <span className="text-[10px] bg-blue-800 text-blue-200 px-1.5 py-0.5 rounded mr-1">AI精選</span>
    : row.is_top_score
    ? <span className="text-[10px] bg-yellow-800 text-yellow-200 px-1.5 py-0.5 rounded mr-1">總分第一</span>
    : null

  return (
    <div className={`rounded-lg p-4 flex gap-2 items-start ${rowBg(row)}`}>
      <span className={`text-lg leading-none mt-0.5 ${dot}`}>●</span>
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start">
          <div className="text-white text-sm font-bold">
            {badge}
            <span
              className="cursor-pointer hover:text-blue-400"
              onClick={() => onResearchStock?.(row.code)}
            >{row.code}</span>{' '}{row.name}{' '}
            <span className="text-gray-400 font-normal">
              [{row.tags || '?'}] B={row.score_b}{row.score_a > 0 ? ` A=${row.score_a}` : ''}{dipStr}{holderStr}
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

export function Result({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [data, setData] = useState<ResultData | null>(null)
  const [dates, setDates] = useState<ResultDateItem[]>([])
  const [selectedDate, setSelectedDate] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [tagFilter, setTagFilter] = useState<TagFilter>('all')

  // 取得可選日期清單，完成後預設選最新一筆
  useEffect(() => {
    axios.get<ResultDateItem[]>('/api/result/dates')
      .then(r => {
        setDates(r.data)
        if (r.data.length > 0) setSelectedDate(r.data[0].date)
      })
      .catch(() => setError(true))
  }, [])

  // 取得選定日期的績效資料
  useEffect(() => {
    if (!selectedDate) return
    setLoading(true)
    setError(false)
    axios.get<ResultData>('/api/result', { params: { pred_date: selectedDate } })
      .then(r => setData(r.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [selectedDate])

  const holdDays = dates.find(d => d.date === selectedDate)?.hold_days ?? null

  const filteredRows = (data?.rows ?? []).filter(row => {
    if (tagFilter === 'all') return true
    return (row.tags || '').includes(tagFilter)
  })

  const avg = filteredRows.length
    ? (filteredRows.reduce((s, r) => s + r.chg_pct, 0) / filteredRows.length).toFixed(2)
    : null

  const winCount = filteredRows.filter(r => r.chg_pct > 0).length

  const labelForDate = (item: ResultDateItem) =>
    `${item.date}（持有${item.hold_days}日）`

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-4 flex items-center gap-4 flex-wrap">
          <h2 className="text-xl font-black text-white">篩選績效</h2>

          {/* 日期選擇（已預設最新日） */}
          <select
            className="bg-gray-800 border border-gray-600 text-gray-200 text-sm rounded px-3 py-1.5 focus:outline-none focus:border-blue-500"
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
          >
            {dates.map(d => (
              <option key={d.date} value={d.date}>{labelForDate(d)}</option>
            ))}
          </select>

          {/* 策略篩選 */}
          <div className="flex gap-1">
            {(['all', 'A', 'B'] as TagFilter[]).map(f => (
              <button
                key={f}
                onClick={() => setTagFilter(f)}
                className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
                  tagFilter === f
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:text-white'
                }`}
              >
                {f === 'all' ? '全部' : `策略${f}`}
              </button>
            ))}
          </div>

          {/* 統計 */}
          {avg !== null && (
            <>
              <span className={`text-sm font-medium ${Number(avg) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                均漲幅 {Number(avg) >= 0 ? '+' : ''}{avg}%
              </span>
              <span className="text-sm text-gray-400">
                勝率 <span className={winCount / filteredRows.length >= 0.5 ? 'text-green-400 font-bold' : 'text-red-400 font-bold'}>
                  {winCount}/{filteredRows.length}
                </span>
                {filteredRows.length > 0 && (
                  <span className="text-gray-500 ml-1">
                    ({Math.round(winCount / filteredRows.length * 100)}%)
                  </span>
                )}
              </span>
            </>
          )}

          {data?.price_date && holdDays !== null && (
            <span className="text-gray-500 text-xs">
              基準收盤 {data.price_date}，持有 {holdDays} 個交易日
            </span>
          )}
        </div>

        {error ? (
          <div className="text-center text-red-400 py-20">載入失敗，請重新整理頁面</div>
        ) : loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : filteredRows.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
        ) : (
          <div className="flex flex-col gap-3">
            {filteredRows.map(row => <RowCard key={row.code} row={row} onResearchStock={onResearchStock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
