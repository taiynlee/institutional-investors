import { useEffect, useState } from 'react'
import axios from 'axios'

interface PoolStock {
  code: string
  name: string
  added_at: string
}

interface FinStatus {
  code: string
  has_revenue: boolean
  has_eps: boolean
  revenue_updated_at?: string | null
  eps_updated_at?: string | null
}

interface SearchResult {
  code: string
  name: string
  sector?: string
  in_pool?: boolean
}

export function StockPoolPage() {
  const [pool, setPool] = useState<PoolStock[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [backfilling, setBackfilling] = useState(false)
  const [backfillNote, setBackfillNote] = useState<string | null>(null)
  const [finStatus, setFinStatus] = useState<Record<string, FinStatus>>({})

  const loadPool = () => {
    setLoading(true)
    axios.get<PoolStock[]>('/api/pool')
      .then(r => setPool(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  const loadFinStatus = () => {
    axios.get<FinStatus[]>('/api/pool/financials-status')
      .then(r => {
        const map: Record<string, FinStatus> = {}
        r.data.forEach(s => { map[s.code] = s })
        setFinStatus(map)
      })
      .catch(() => {})
  }

  useEffect(() => { loadPool(); loadFinStatus() }, [])

  useEffect(() => {
    if (query.length < 1) {
      setSearchResults([])
      setSearched(false)
    }
  }, [query])

  const addStock = async (code: string, name: string) => {
    try {
      await axios.post('/api/pool', { code, name })
      setQuery('')
      setSearchResults([])
      setSearched(false)
      loadPool()
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? '新增失敗')
    }
  }

  const doSearch = () => {
    if (!query.trim()) return
    setSearching(true)
    setSearched(false)
    axios.get<SearchResult[]>('/api/stocks/search', { params: { q: query } })
      .then(r => { setSearchResults(r.data); setSearched(true) })
      .catch(() => {})
      .finally(() => setSearching(false))
  }

  const removeSelected = async () => {
    if (selected.size === 0) return
    if (!confirm(`確定移除 ${selected.size} 支股票？`)) return
    await Promise.all([...selected].map(code =>
      axios.delete(`/api/pool/${code}`).catch(() => {})
    ))
    setSelected(new Set())
    loadPool()
  }

  const toggleSelect = (code: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(code) ? next.delete(code) : next.add(code)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === pool.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(pool.map(s => s.code)))
    }
  }

  const backfillAll = async () => {
    if (!confirm(`補抓全部 ${pool.length} 支股票的月營收 + 季報 EPS？背景執行，速率限制約每股 13 秒，完成需數分鐘。`)) return
    setBackfilling(true)
    setBackfillNote(null)
    try {
      const r = await axios.post('/api/admin/backfill_pool_financials')
      setBackfillNote(`✓ 已觸發補抓 ${r.data.codes} 支股票（背景執行中）`)
    } catch (e: any) {
      setBackfillNote(`✕ ${e?.response?.data?.detail ?? '觸發失敗'}`)
    } finally {
      setBackfilling(false)
    }
  }

  const backfillMissing = async () => {
    setBackfilling(true)
    setBackfillNote(null)
    try {
      const r = await axios.post('/api/pool/backfill-missing')
      if (r.data.missing === 0) {
        setBackfillNote('✓ 全部股票均有月營收和季EPS，無需補抓')
      } else {
        setBackfillNote(`✓ 補抓 ${r.data.missing} 支缺失股票（背景執行中）`)
      }
      setTimeout(loadFinStatus, 3000)
    } catch (e: any) {
      setBackfillNote(`✕ ${e?.response?.data?.detail ?? '觸發失敗'}`)
    } finally {
      setBackfilling(false)
    }
  }

  const missingCount = pool.filter(s => {
    const fs = finStatus[s.code]
    return !fs || !fs.has_revenue || !fs.has_eps
  }).length

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">股票池管理</h1>
            <p className="text-gray-400 text-sm mt-1">共 {pool.length} 支追蹤股票</p>
          </div>
          <div className="flex gap-2 items-center flex-wrap justify-end">
            {backfillNote && <span className={`text-xs ${backfillNote.startsWith('✓') ? 'text-green-400' : 'text-red-400'}`}>{backfillNote}</span>}
            {missingCount > 0 && (
              <button
                onClick={backfillMissing}
                disabled={backfilling}
                className="px-3 py-1.5 text-sm bg-yellow-700 hover:bg-yellow-600 text-white rounded disabled:opacity-50"
              >
                {backfilling ? '補抓中...' : `補抓缺失 (${missingCount}支)`}
              </button>
            )}
            <button
              onClick={backfillAll}
              disabled={backfilling || pool.length === 0}
              className="px-3 py-1.5 text-sm bg-blue-800 hover:bg-blue-700 text-white rounded disabled:opacity-50"
            >
              {backfilling ? '補抓中...' : '補抓全部財務'}
            </button>
            {selected.size > 0 && (
              <button
                onClick={removeSelected}
                className="px-3 py-1.5 text-sm bg-red-700 hover:bg-red-600 text-white rounded"
              >
                移除 ({selected.size})
              </button>
            )}
          </div>
        </div>

        {/* 搜尋新增 */}
        <div className="mb-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doSearch()}
              placeholder="輸入股票代碼或名稱查詢"
              className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={doSearch}
              disabled={searching || !query.trim()}
              className="px-5 py-2.5 bg-blue-700 hover:bg-blue-600 text-white rounded-lg text-sm font-medium disabled:opacity-50"
            >
              {searching ? '查詢中...' : '查詢'}
            </button>
          </div>
          {/* 查詢結果 */}
          {searched && (
            <div className="mt-2 bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
              {searchResults.length === 0 ? (
                <div className="px-4 py-3 text-gray-500 text-sm">
                  查無股票「{query}」，請確認代碼或名稱
                </div>
              ) : (
                searchResults.map(r => (
                  <div
                    key={r.code}
                    className="px-4 py-3 flex items-center gap-3 border-b border-gray-800 last:border-0"
                  >
                    <span className="font-mono text-blue-300 w-16 shrink-0 text-base font-bold">{r.code}</span>
                    <span className="text-white flex-1">{r.name}</span>
                    {r.sector && <span className="text-gray-500 text-xs">{r.sector}</span>}
                    {r.in_pool
                      ? <span className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">已在池中</span>
                      : (
                        <button
                          onClick={() => addStock(r.code, r.name)}
                          className="px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white text-sm rounded font-medium"
                        >
                          ＋ 加入池
                        </button>
                      )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* 表格 */}
        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : (
          <div className="bg-gray-900 rounded-xl overflow-hidden border border-gray-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={selected.size === pool.length && pool.length > 0}
                      onChange={toggleAll}
                      className="accent-blue-500"
                    />
                  </th>
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-left">加入時間</th>
                  <th className="px-4 py-3 text-center">月營收</th>
                  <th className="px-4 py-3 text-center">季EPS</th>
                  <th className="px-4 py-3 text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {pool.map(stock => (
                  <tr
                    key={stock.code}
                    className={`border-b border-gray-800 hover:bg-gray-800 transition-colors ${selected.has(stock.code) ? 'bg-blue-950' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(stock.code)}
                        onChange={() => toggleSelect(stock.code)}
                        className="accent-blue-500"
                      />
                    </td>
                    <td className="px-4 py-3 font-mono text-blue-300 font-bold">{stock.code}</td>
                    <td className="px-4 py-3 text-white">{stock.name}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {stock.added_at ? new Date(stock.added_at).toLocaleDateString('zh-TW') : '—'}
                    </td>
                    <td className="px-4 py-3 text-center text-xs">
                      {finStatus[stock.code]
                        ? (finStatus[stock.code].has_revenue
                            ? <span className="text-green-400" title={finStatus[stock.code].revenue_updated_at ?? ''}>✔ <span className="text-gray-500">{finStatus[stock.code].revenue_updated_at}</span></span>
                            : <span className="text-red-400">✘</span>)
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center text-xs">
                      {finStatus[stock.code]
                        ? (finStatus[stock.code].has_eps
                            ? <span className="text-green-400" title={finStatus[stock.code].eps_updated_at ?? ''}>✔ <span className="text-gray-500">{finStatus[stock.code].eps_updated_at}</span></span>
                            : <span className="text-red-400">✘</span>)
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={async () => {
                          await axios.delete(`/api/pool/${stock.code}`)
                          loadPool()
                        }}
                        className="text-xs text-red-500 hover:text-red-400"
                      >
                        移除
                      </button>
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
