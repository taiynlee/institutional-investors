import { useEffect, useState } from 'react'
import axios from 'axios'
import type { IcChainGroup } from '../types'

const NODE_COLORS: Record<string, string> = {
  上游: 'bg-blue-900 text-blue-300 border-blue-700',
  中游: 'bg-yellow-900 text-yellow-300 border-yellow-700',
  下游: 'bg-green-900 text-green-300 border-green-700',
}

function IcGroupCard({ group, poolCodes, onResearchStock }: {
  group: IcChainGroup
  poolCodes: Set<string>
  onResearchStock?: (code: string) => void
}) {
  const [open, setOpen] = useState(false)
  const poolCount = group.companies.filter(c => poolCodes.has(c.code)).length
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
      <button
        className="w-full px-4 py-3 flex justify-between items-center hover:bg-gray-800 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-3">
          <span className="text-white font-bold">{group.ic_name}</span>
          {group.ic_parent && (
            <span className="text-xs text-gray-500">{group.ic_parent}</span>
          )}
          <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">
            {group.companies.length} 家
          </span>
          {poolCount > 0 && (
            <span className="text-xs bg-blue-900 text-blue-300 px-2 py-0.5 rounded-full">
              池 {poolCount}
            </span>
          )}
        </div>
        <span className="text-gray-500">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-gray-700">
          <div className="flex flex-wrap gap-2 pt-3">
            {group.companies.map(c => {
              const inPool = poolCodes.has(c.code)
              const pos = c.ic_node?.includes('上游') ? '上游' : c.ic_node?.includes('下游') ? '下游' : c.ic_node ? '中游' : null
              const colorClass = inPool
                ? (pos ? NODE_COLORS[pos] : 'bg-gray-800 text-gray-300 border-gray-600')
                : 'bg-gray-900 text-gray-500 border-gray-700'
              return (
                <div
                  key={c.code}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs ${inPool ? 'cursor-pointer hover:opacity-80' : 'cursor-default'} ${colorClass}`}
                  onClick={() => inPool && onResearchStock?.(c.code)}
                >
                  <span className="font-mono font-bold">{c.code}</span>
                  <span>{c.name}</span>
                  {inPool && pos && <span className="text-[10px] opacity-70">{pos}</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function IcChain({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [groups, setGroups] = useState<IcChainGroup[]>([])
  const [poolCodes, setPoolCodes] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      axios.get<IcChainGroup[]>('/api/ic-chains'),
      axios.get<{ code: string }[]>('/api/pool'),
    ]).then(([ic, pool]) => {
      setGroups(ic.data)
      setPoolCodes(new Set(pool.data.map(p => p.code)))
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const filtered = search
    ? groups.filter(g =>
        g.ic_name.includes(search) ||
        g.ic_parent?.includes(search) ||
        g.companies.some(c => c.code.includes(search) || c.name.includes(search))
      )
    : groups

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">電子科技產業鏈</h1>
            <p className="text-gray-400 text-sm">資料來源：ic.tpex.org.tw，每半年更新</p>
          </div>
          <input
            type="text"
            placeholder="搜尋產業 / 代碼 / 名稱"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-lg px-3 py-1.5 w-52 focus:outline-none focus:border-blue-500"
          />
        </div>

        <div className="flex gap-3 mb-4 flex-wrap">
          {Object.entries(NODE_COLORS).map(([pos, cls]) => (
            <span key={pos} className={`text-xs px-2.5 py-1 rounded-lg border ${cls}`}>{pos}</span>
          ))}
          <span className="text-xs text-gray-500 self-center ml-2">{filtered.length} 個產業鏈</span>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center text-gray-500 py-20">無資料</div>
        ) : (
          <div className="flex flex-col gap-3">
            {filtered.map(g => <IcGroupCard key={g.ic_code} group={g} poolCodes={poolCodes} onResearchStock={onResearchStock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
