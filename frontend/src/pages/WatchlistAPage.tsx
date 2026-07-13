import { useEffect, useState } from 'react'
import axios from 'axios'
import type { WatchlistAItem } from '../types'

type TabStatus = 'active' | 'tracking' | 'triggered' | 'entered' | 'all'

const TAB_LABELS: Record<TabStatus, string> = {
  active:    '追蹤中+到位',
  tracking:  '追蹤中',
  triggered: '已到位',
  entered:   '已進場',
  all:       '全部',
}

const STATUS_LABELS: Record<string, string> = {
  tracking:     '追蹤中',
  triggered:    '已到位',
  entered:      '已進場',
  exited:       '已出場',
  dismissed:    '已忽略',
  expired:      '到期',
  auto_removed: '自動移除',
}

const STATUS_COLORS: Record<string, string> = {
  tracking:     'text-yellow-400',
  triggered:    'text-green-400',
  entered:      'text-blue-400',
  exited:       'text-gray-400',
  dismissed:    'text-gray-500',
  expired:      'text-gray-600',
  auto_removed: 'text-gray-600',
}

export function WatchlistAPage({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [items, setItems] = useState<WatchlistAItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [tab, setTab] = useState<TabStatus>('active')
  const [updating, setUpdating] = useState<number | null>(null)

  const fetchData = (t: TabStatus) => {
    setLoading(true)
    setError(false)
    const params: Record<string, string> = {}
    if (t === 'active') {
      // 不傳 status，後端預設過濾 expired/auto_removed
    } else if (t === 'all') {
      params.include_expired = 'true'
    } else {
      params.status = t
    }
    axios.get<WatchlistAItem[]>('/api/watchlist-a', { params })
      .then(r => setItems(r.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData(tab) }, [tab])

  const patchStatus = async (id: number, status: string) => {
    setUpdating(id)
    try {
      await axios.patch(`/api/watchlist-a/${id}/status`, { status })
      fetchData(tab)
    } catch {
      alert('更新失敗')
    } finally {
      setUpdating(null)
    }
  }

  const filtered = tab === 'active'
    ? items.filter(i => i.status === 'tracking' || i.status === 'triggered')
    : items

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-4">
          <h1 className="text-2xl font-black text-white">策略A 追蹤清單</h1>
          <p className="text-gray-400 text-sm">曾出現策略A訊號，等待BB拉回≤5的進場時機</p>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 mb-4">
          {(Object.keys(TAB_LABELS) as TabStatus[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                tab === t
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white'
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : error ? (
          <div className="text-center text-red-400 py-20">載入失敗，請重新整理頁面</div>
        ) : filtered.length === 0 ? (
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
                  <th className="px-4 py-3 text-right">現BB</th>
                  <th className="px-4 py-3 text-right">到位日</th>
                  <th className="px-4 py-3 text-right">到位收盤</th>
                  <th className="px-4 py-3 text-right">現價</th>
                  <th className="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(item => {
                  const chgColor = item.chg_pct === null ? '' : item.chg_pct >= 0 ? 'text-red-400' : 'text-green-400'
                  const bbColor = item.current_bb === null ? 'text-gray-500'
                    : item.current_bb <= 2 ? 'text-green-400 font-bold'
                    : item.current_bb <= 5 ? 'text-yellow-400'
                    : 'text-gray-400'
                  return (
                    <tr key={item.id} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                      <td
                        className="px-4 py-3 font-mono text-blue-300 font-bold cursor-pointer hover:text-blue-400"
                        onClick={() => onResearchStock?.(item.code)}
                      >{item.code}</td>
                      <td className="px-4 py-3 text-white">{item.name}</td>
                      <td className={`px-4 py-3 text-xs ${STATUS_COLORS[item.status] ?? 'text-gray-400'}`}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{item.added_date}</td>
                      <td className="px-4 py-3 text-right text-gray-300">{item.added_close}</td>
                      <td className="px-4 py-3 text-right text-gray-300">
                        {item.added_bb_position.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 text-right text-blue-300 font-bold">
                        {item.added_score_a.toFixed(0)}
                      </td>
                      <td className={`px-4 py-3 text-right ${bbColor}`}>
                        {item.current_bb !== null ? item.current_bb.toFixed(1) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-400 text-xs">
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
                              <span className="text-xs ml-1">
                                ({item.chg_pct >= 0 ? '+' : ''}{item.chg_pct.toFixed(2)}%
                                <span className="text-gray-500 ml-0.5">
                                  {item.chg_basis === 'triggered' ? '進' : '加'}
                                </span>)
                              </span>
                            )}
                          </span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {item.status === 'triggered' && (
                          <div className="flex gap-1 justify-end">
                            <button
                              disabled={updating === item.id}
                              onClick={() => patchStatus(item.id, 'entered')}
                              className="px-2 py-0.5 text-xs bg-blue-700 hover:bg-blue-600 rounded disabled:opacity-50"
                            >進場</button>
                            <button
                              disabled={updating === item.id}
                              onClick={() => patchStatus(item.id, 'dismissed')}
                              className="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 rounded disabled:opacity-50"
                            >忽略</button>
                          </div>
                        )}
                        {item.status === 'entered' && (
                          <button
                            disabled={updating === item.id}
                            onClick={() => patchStatus(item.id, 'exited')}
                            className="px-2 py-0.5 text-xs bg-gray-700 hover:bg-gray-600 rounded disabled:opacity-50"
                          >出場</button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
