import { useEffect, useState } from 'react'
import axios from 'axios'
import type { WatchlistAItem } from '../types'

async function patchStatus(id: number, status: string) {
  await axios.patch(`/api/watchlist-a/${id}/status`, { status })
}

const STATUS_LABEL: Record<string, string> = {
  tracking: '觀察中',
  triggered: '已到位',
  entered: '已進場',
  exited: '已出場',
  dismissed: '已略過',
}

const STATUS_COLOR: Record<string, string> = {
  tracking: 'bg-blue-900 text-blue-300 border-blue-700',
  triggered: 'bg-green-900 text-green-300 border-green-700',
  entered: 'bg-yellow-900 text-yellow-300 border-yellow-700',
  exited: 'bg-gray-700 text-gray-400 border-gray-600',
  dismissed: 'bg-gray-800 text-gray-600 border-gray-700',
}

function ItemRow({
  item,
  onResearchStock,
  onStatusChange,
}: {
  item: WatchlistAItem
  onResearchStock?: (code: string) => void
  onStatusChange: (id: number, status: string) => void
}) {
  const statusCls = STATUS_COLOR[item.status] ?? 'bg-gray-700 text-gray-400 border-gray-600'
  const statusLabel = STATUS_LABEL[item.status] ?? item.status
  const chgColor = item.chg_pct === null ? '' : item.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'

  const nextActions = item.status === 'triggered'
    ? [{ label: '確認進場', status: 'entered' }]
    : item.status === 'entered'
    ? [{ label: '已出場', status: 'exited' }]
    : item.status === 'tracking'
    ? [{ label: '略過', status: 'dismissed' }]
    : []

  return (
    <tr className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
      <td
        className="px-4 py-3 font-mono text-blue-300 font-bold cursor-pointer hover:text-blue-400"
        onClick={() => onResearchStock?.(item.code)}
      >{item.code}</td>
      <td className="px-4 py-3 text-white">{item.name}</td>
      <td className="px-4 py-3">
        <span className={`text-xs px-2 py-0.5 rounded border ${statusCls}`}>{statusLabel}</span>
      </td>
      <td className="px-4 py-3 text-gray-400 text-sm">{item.added_date}</td>
      <td className="px-4 py-3 text-right text-gray-300">{item.added_close}</td>
      <td className="px-4 py-3 text-right text-gray-300">
        {item.added_bb_position.toFixed(1)}
      </td>
      <td className="px-4 py-3 text-right text-blue-300 font-bold">
        {item.added_score_a.toFixed(0)}
      </td>
      <td className="px-4 py-3 text-right text-gray-400 text-sm">
        {item.triggered_date ?? '—'}
      </td>
      <td className="px-4 py-3 text-right">
        {item.triggered_close ? (
          <span className="text-green-400">{item.triggered_close}</span>
        ) : '—'}
      </td>
      <td className="px-4 py-3 text-right">
        {item.current_close ? (
          <span className={chgColor}>
            {item.current_close}
            {item.chg_pct !== null && (
              <span className="text-xs ml-1">({item.chg_pct >= 0 ? '+' : ''}{item.chg_pct?.toFixed(2)}%)</span>
            )}
          </span>
        ) : '—'}
      </td>
      <td className="px-4 py-3">
        <div className="flex gap-1">
          {nextActions.map(a => (
            <button
              key={a.status}
              onClick={() => onStatusChange(item.id, a.status)}
              className="text-[10px] px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded border border-gray-600"
            >
              {a.label}
            </button>
          ))}
        </div>
      </td>
    </tr>
  )
}

export function WatchlistAPage({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [items, setItems] = useState<WatchlistAItem[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)

  const loadItems = (filter: string) => {
    setLoading(true)
    const params = filter ? { status: filter } : {}
    axios.get<WatchlistAItem[]>('/api/watchlist-a', { params })
      .then(r => setItems(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadItems(statusFilter) }, [statusFilter])

  const handleStatusChange = async (id: number, status: string) => {
    await patchStatus(id, status)
    loadItems(statusFilter)
  }

  const counts = items.reduce((acc, i) => {
    acc[i.status] = (acc[i.status] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">策略A 追蹤清單</h1>
            <p className="text-gray-400 text-sm">曾出現策略A訊號，等待BB拉回≤5的進場時機</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setStatusFilter('')}
              className={`px-3 py-1 text-sm rounded ${!statusFilter ? 'bg-blue-600' : 'bg-gray-800 text-gray-400'}`}
            >
              全部 ({items.length})
            </button>
            {Object.entries(STATUS_LABEL).map(([k, v]) => (
              <button
                key={k}
                onClick={() => setStatusFilter(k === statusFilter ? '' : k)}
                className={`px-3 py-1 text-sm rounded ${statusFilter === k ? 'bg-blue-600' : 'bg-gray-800 text-gray-400 hover:text-white'}`}
              >
                {v} ({counts[k] ?? 0})
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : items.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
        ) : (
          <div className="bg-gray-900 rounded-xl overflow-x-auto border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-left">狀態</th>
                  <th className="px-4 py-3 text-left">加入日</th>
                  <th className="px-4 py-3 text-right">加入收盤</th>
                  <th className="px-4 py-3 text-right">加入BB</th>
                  <th className="px-4 py-3 text-right">A分</th>
                  <th className="px-4 py-3 text-right">到位日</th>
                  <th className="px-4 py-3 text-right">到位收盤</th>
                  <th className="px-4 py-3 text-right">現價</th>
                  <th className="px-4 py-3 text-left">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map(item => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    onResearchStock={onResearchStock}
                    onStatusChange={handleStatusChange}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
