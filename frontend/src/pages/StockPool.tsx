import { useEffect, useState, useRef } from 'react'
import axios from 'axios'

interface PoolStock {
  code: string
  name: string
  added_at: string
}

interface SearchResult {
  code: string
  name: string
}

export function StockPoolPage() {
  const [pool, setPool] = useState<PoolStock[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const searchRef = useRef<HTMLDivElement>(null)

  const loadPool = () => {
    setLoading(true)
    axios.get<PoolStock[]>('/api/pool')
      .then(r => setPool(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadPool() }, [])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (query.length < 1) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    setSearching(true)
    const t = setTimeout(() => {
      axios.get<SearchResult[]>('/api/stocks/search', { params: { q: query } })
        .then(r => { setSearchResults(r.data); setShowDropdown(true) })
        .catch(() => {})
        .finally(() => setSearching(false))
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  const addStock = async (code: string, name: string) => {
    try {
      await axios.post('/api/pool', { code, name })
      setQuery('')
      setShowDropdown(false)
      loadPool()
    } catch (e: any) {
      alert(e?.response?.data?.detail ?? '新增失敗')
    }
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

  const poolSet = new Set(pool.map(s => s.code))

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">股票池管理</h1>
            <p className="text-gray-400 text-sm mt-1">共 {pool.length} 支追蹤股票</p>
          </div>
          <div className="flex gap-2">
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
        <div className="mb-4" ref={searchRef}>
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="搜尋股票代碼或名稱（輸入後選取新增）"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
            />
            {searching && (
              <span className="absolute right-3 top-3 text-gray-500 text-xs">搜尋中...</span>
            )}
            {showDropdown && (searchResults.length > 0 || (!searching && query.length > 0)) && (
              <div className="absolute z-20 w-full mt-1 bg-gray-800 border border-gray-700 rounded-lg overflow-hidden shadow-xl">
                {searchResults.map(r => (
                  <button
                    key={r.code}
                    onClick={() => addStock(r.code, r.name)}
                    className={`w-full text-left px-4 py-2 hover:bg-gray-700 flex justify-between items-center ${poolSet.has(r.code) ? 'opacity-40' : ''}`}
                    disabled={poolSet.has(r.code)}
                  >
                    <span className="font-mono text-blue-300">{r.code}</span>
                    <span className="text-gray-300">{r.name}</span>
                    {poolSet.has(r.code) && <span className="text-xs text-gray-500">已在池中</span>}
                  </button>
                ))}
                {!searching && (
                  <button
                    onClick={() => addStock(query.trim(), query.trim())}
                    className="w-full text-left px-4 py-2 hover:bg-gray-700 border-t border-gray-700 text-blue-400 text-sm"
                  >
                    + 直接新增代碼「{query.trim()}」
                  </button>
                )}
              </div>
            )}
          </div>
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
