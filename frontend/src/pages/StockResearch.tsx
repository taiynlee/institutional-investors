import { useEffect, useState } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts'

interface Snapshot {
  code: string
  name: string
  sector: string
  market: string
  capital: number
  tags: string[]
  price: { close: number | null; high: number | null; low: number | null; volume: number | null; date: string | null }
  inst: { foreign_net: number | null; trust_net: number | null; three_major_net: number | null; date: string | null }
  shareholding: { pct_1000_lot: number | null; pct_400_lot: number | null; date: string | null }
  screen: { bb_position: number; bb_peak: number; score_a: number; score_b: number; tags: string[] } | null
}

interface InstRow {
  date: string
  foreign_net: number
  trust_net: number
  dealer_net: number
  net: number
}

interface Fins {
  revenue: { year: number; month: number; revenue: number }[]
  eps: { year: number; quarter: number; eps: number; revenue: number; op_income: number; net_income: number }[]
}

interface Level {
  price: number
  type: 'support' | 'resistance'
  strength: number
}

interface Levels {
  current_price: number
  supports: Level[]
  resistances: Level[]
}

function Tag({ label }: { label: string }) {
  return (
    <span className="text-[10px] px-1.5 py-0.5 bg-gray-700 text-gray-300 rounded border border-gray-600">
      {label}
    </span>
  )
}

function InstChart({ data }: { data: InstRow[] }) {
  return (
    <ResponsiveContainer width="100%" height={120}>
      <BarChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#6b7280' }} tickFormatter={d => d.slice(5)} />
        <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
          formatter={(v: number) => [`${v > 0 ? '+' : ''}${v}張`, '']}
          labelStyle={{ color: '#9ca3af' }}
        />
        <ReferenceLine y={0} stroke="#374151" />
        <Bar dataKey="foreign_net" name="外資" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.foreign_net >= 0 ? '#ef4444' : '#22c55e'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

function RevenueChart({ data }: { data: { year: number; month: number; revenue: number }[] }) {
  const chartData = [...data].reverse().slice(-12).map(r => ({
    label: `${r.year}/${String(r.month).padStart(2, '0')}`,
    revenue: Math.round(r.revenue / 1000),
  }))
  return (
    <ResponsiveContainer width="100%" height={110}>
      <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
        <XAxis dataKey="label" tick={{ fontSize: 9, fill: '#6b7280' }} />
        <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} />
        <Tooltip
          contentStyle={{ background: '#111827', border: '1px solid #374151', fontSize: 11 }}
          formatter={(v: number) => [`${v}百萬`, '月營收']}
          labelStyle={{ color: '#9ca3af' }}
        />
        <Bar dataKey="revenue" fill="#3b82f6" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function StockResearch({ code, onClose }: { code: string; onClose: () => void }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [instFlow, setInstFlow] = useState<InstRow[]>([])
  const [fins, setFins] = useState<Fins | null>(null)
  const [levels, setLevels] = useState<Levels | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get<Snapshot>(`/api/stock-snapshot/${code}`),
      axios.get<InstRow[]>(`/api/inst-flow/${code}`, { params: { days: 20 } }),
      axios.get<Fins>(`/api/fins/${code}`),
      axios.get<Levels>(`/api/stock-levels/${code}`),
    ]).then(([s, i, f, l]) => {
      setSnapshot(s.data)
      setInstFlow(i.data)
      setFins(f.data)
      setLevels(l.data)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [code])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 overflow-y-auto py-8" onClick={onClose}>
      <div
        className="w-full max-w-4xl mx-4 bg-gray-950 border border-gray-700 rounded-2xl shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center p-5 border-b border-gray-800">
          <div>
            <span className="text-xl font-black text-white">{code}</span>
            {snapshot && (
              <>
                <span className="text-gray-400 ml-2">{snapshot.name}</span>
                <span className="text-gray-600 text-xs ml-2">{snapshot.sector}</span>
              </>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-2xl leading-none">×</button>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : !snapshot ? (
          <div className="text-center text-gray-500 py-20">查無資料</div>
        ) : (
          <div className="p-5 grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* 左欄 */}
            <div className="space-y-4">
              {/* 行情快照 */}
              <div className="bg-gray-900 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-3">行情快照 {snapshot.price.date}</div>
                <div className="grid grid-cols-3 gap-3 text-center mb-3">
                  <div>
                    <div className="text-2xl font-black text-white">{snapshot.price.close ?? '—'}</div>
                    <div className="text-xs text-gray-500">收盤</div>
                  </div>
                  <div>
                    <div className="text-sm text-red-400 font-bold">{snapshot.price.high ?? '—'}</div>
                    <div className="text-xs text-gray-500">最高</div>
                  </div>
                  <div>
                    <div className="text-sm text-green-400 font-bold">{snapshot.price.low ?? '—'}</div>
                    <div className="text-xs text-gray-500">最低</div>
                  </div>
                </div>
                {snapshot.screen && (
                  <div className="grid grid-cols-2 gap-2 text-xs mt-2">
                    <div className="bg-gray-800 rounded p-2 text-center">
                      <div className="text-blue-400 font-bold text-base">{snapshot.screen.score_a.toFixed(0)}</div>
                      <div className="text-gray-500">策略A分</div>
                    </div>
                    <div className="bg-gray-800 rounded p-2 text-center">
                      <div className="text-yellow-400 font-bold text-base">{snapshot.screen.score_b.toFixed(0)}</div>
                      <div className="text-gray-500">策略B分</div>
                    </div>
                    <div className="bg-gray-800 rounded p-2 text-center">
                      <div className="text-white font-bold text-base">{snapshot.screen.bb_position.toFixed(1)}</div>
                      <div className="text-gray-500">BB位置</div>
                    </div>
                    <div className="bg-gray-800 rounded p-2 text-center">
                      <div className="text-white font-bold text-base">{snapshot.screen.bb_peak.toFixed(1)}</div>
                      <div className="text-gray-500">BB高點</div>
                    </div>
                  </div>
                )}
              </div>

              {/* 大戶持股 */}
              <div className="bg-gray-900 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-2">大戶持股 {snapshot.shareholding.date}</div>
                <div className="flex gap-4">
                  <div className="text-center">
                    <div className="text-lg font-bold text-teal-400">{snapshot.shareholding.pct_1000_lot?.toFixed(1) ?? '—'}%</div>
                    <div className="text-xs text-gray-500">千張以上</div>
                  </div>
                  <div className="text-center">
                    <div className="text-lg font-bold text-cyan-400">{snapshot.shareholding.pct_400_lot?.toFixed(1) ?? '—'}%</div>
                    <div className="text-xs text-gray-500">400張以上</div>
                  </div>
                </div>
              </div>

              {/* 法人流向圖 */}
              <div className="bg-gray-900 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-2">外資買賣超（近20日）</div>
                {instFlow.length > 0 ? <InstChart data={instFlow} /> : <div className="text-gray-600 text-xs py-4 text-center">無資料</div>}
              </div>

              {/* 公司標籤 */}
              {snapshot.tags.length > 0 && (
                <div className="bg-gray-900 rounded-xl p-4">
                  <div className="text-xs text-gray-500 mb-2">公司標籤</div>
                  <div className="flex flex-wrap gap-1.5">
                    {snapshot.tags.map(t => <Tag key={t} label={t} />)}
                  </div>
                </div>
              )}
            </div>

            {/* 右欄 */}
            <div className="space-y-4">
              {/* 支撐壓力 */}
              {levels && (
                <div className="bg-gray-900 rounded-xl p-4">
                  <div className="text-xs text-gray-500 mb-3">支撐 / 壓力位階（現價 {levels.current_price}）</div>
                  <div className="space-y-1.5">
                    {levels.resistances.slice(0, 3).map((l, i) => (
                      <div key={i} className="flex justify-between items-center text-xs">
                        <span className="text-red-400 font-mono">{l.price.toFixed(2)}</span>
                        <div className="flex-1 mx-2 h-1 bg-gray-800 rounded overflow-hidden">
                          <div className="h-full bg-red-800 rounded" style={{ width: `${Math.min(l.strength * 100, 100)}%` }} />
                        </div>
                        <span className="text-gray-500">壓力{i + 1}</span>
                      </div>
                    ))}
                    <div className="border-t border-gray-700 my-2 text-center text-xs text-white font-bold">
                      {levels.current_price}
                    </div>
                    {levels.supports.slice(0, 3).map((l, i) => (
                      <div key={i} className="flex justify-between items-center text-xs">
                        <span className="text-green-400 font-mono">{l.price.toFixed(2)}</span>
                        <div className="flex-1 mx-2 h-1 bg-gray-800 rounded overflow-hidden">
                          <div className="h-full bg-green-800 rounded" style={{ width: `${Math.min(l.strength * 100, 100)}%` }} />
                        </div>
                        <span className="text-gray-500">支撐{i + 1}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 月營收圖 */}
              {fins && fins.revenue.length > 0 && (
                <div className="bg-gray-900 rounded-xl p-4">
                  <div className="text-xs text-gray-500 mb-2">月營收（近12月）</div>
                  <RevenueChart data={fins.revenue} />
                </div>
              )}

              {/* 季EPS */}
              {fins && fins.eps.length > 0 && (
                <div className="bg-gray-900 rounded-xl p-4">
                  <div className="text-xs text-gray-500 mb-2">季報EPS（近8季）</div>
                  <div className="space-y-1.5">
                    {fins.eps.slice(0, 8).map((e, i) => (
                      <div key={i} className="flex justify-between items-center text-xs">
                        <span className="text-gray-400">{e.year}Q{e.quarter}</span>
                        <span className={`font-bold font-mono ${e.eps > 0 ? 'text-red-400' : 'text-green-400'}`}>
                          {e.eps > 0 ? '+' : ''}{e.eps.toFixed(2)}
                        </span>
                        <span className="text-gray-600">{(e.revenue / 1000).toFixed(0)}M</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
