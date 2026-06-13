import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

const API = '/fubon-api'

type SubTab = 'live' | 'trades' | 'pre-session' | 'params' | 'config' | 'health'

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: 'live',        label: '今日交易' },
  { id: 'trades',      label: '交易紀錄' },
  { id: 'pre-session', label: '盤前狀況' },
  { id: 'params',      label: '交易設定' },
  { id: 'config',      label: '系統設定' },
  { id: 'health',      label: '系統健診' },
]

// ── Shared styles ─────────────────────────────────────────────────────────────
const card = 'bg-[#142035] border border-[#253d5c] rounded-xl'
const muted = 'text-[#6b84a0]'
const mono  = 'font-mono tabular-nums'

function MetricCard({ label, value, sub, color }: {
  label: string; value: string | number; sub?: string; color?: string
}) {
  return (
    <div className={`${card} p-4 flex flex-col`}>
      <div className={`text-[10px] uppercase tracking-widest ${muted} mb-1`}>{label}</div>
      <div className={`text-2xl font-bold ${mono} ${color ?? 'text-[#dde6f0]'}`}>{value}</div>
      {sub && <div className={`text-xs ${muted} mt-0.5`}>{sub}</div>}
    </div>
  )
}

function Badge({ text, color }: { text: string; color?: string }) {
  const cls = color === 'green' ? 'bg-green-400/15 text-green-400'
    : color === 'red'   ? 'bg-red-400/15 text-red-400'
    : color === 'blue'  ? 'bg-blue-400/15 text-blue-400'
    : color === 'yellow'? 'bg-yellow-400/15 text-yellow-400'
    : 'bg-[#253d5c] text-[#6b84a0]'
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold ${cls}`}>{text}</span>
}

function SectionLabel({ children }: { children: string }) {
  return (
    <div className={`text-[10px] uppercase tracking-[.5px] ${muted} mb-1.5`}>{children}</div>
  )
}

// ── 今日交易 ─────────────────────────────────────────────────────────────────
function LiveTab() {
  const [list, setList] = useState<any | null>(null)
  const [dates, setDates] = useState<{ date: string; count: number }[]>([])
  const [selDate, setSelDate] = useState('')
  const [status, setStatus] = useState<{ total_pnl: number; trade_count: number } | null>(null)
  const [positions, setPositions] = useState<any[]>([])
  const [ticks, setTicks] = useState<Record<string, any>>({})
  const evsRef = useRef<EventSource | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get(`${API}/daytrade-list/dates`).then(r => {
      setDates(r.data)
      if (r.data.length > 0 && !selDate) setSelDate(r.data[0].date)
    }).catch(() => {})
    axios.get(`${API}/status`).then(r => setStatus(r.data)).catch(() => {})
    axios.get(`${API}/positions`).then(r => setPositions(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selDate) return
    setLoading(true)
    axios.get(`${API}/daytrade-list?date_str=${selDate}`)
      .then(r => setList(r.data))
      .catch(() => setList(null))
      .finally(() => setLoading(false))
  }, [selDate])

  // SSE for live tick prices
  useEffect(() => {
    if (!list?.stocks?.length) return
    const syms = list.stocks.map((s: any) => s.stock_id).join(',')
    if (evsRef.current) evsRef.current.close()
    const evs = new EventSource(`${API}/stream?syms=${syms}`)
    evs.onmessage = e => { try { setTicks(JSON.parse(e.data)) } catch {} }
    evsRef.current = evs
    return () => evs.close()
  }, [list?.date])

  const pnlColor = (v: number) => v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-[#6b84a0]'
  const chgColor = (v: number) => v >= 0 ? 'text-green-400' : 'text-red-400'

  const stocks: any[] = list?.stocks ?? []

  return (
    <div className="space-y-4">
      {/* 頂部: 損益 + 持倉 */}
      {(status || positions.length > 0) && (
        <div className="grid grid-cols-3 gap-3">
          <MetricCard label="今日損益" value={`${(status?.total_pnl ?? 0) >= 0 ? '+' : ''}${(status?.total_pnl ?? 0).toLocaleString()}`} sub={`${status?.trade_count ?? 0} 筆`} color={pnlColor(status?.total_pnl ?? 0)} />
          <MetricCard label="持倉數" value={positions.length} color="text-[#60a5fa]" />
          <MetricCard label="模式" value="🔵 DRY RUN" color="text-blue-400" />
        </div>
      )}

      {/* 持倉明細（若有） */}
      {positions.length > 0 && (
        <div className={card}>
          <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>持倉</div>
          <table className="w-full text-sm">
            <thead>
              <tr className={`text-[11px] ${muted} border-b border-[#253d5c]`}>
                <th className="px-4 py-2 text-left">代號</th>
                <th className="px-4 py-2 text-right">張</th>
                <th className="px-4 py-2 text-right">成本</th>
                <th className="px-4 py-2 text-right">現價</th>
                <th className="px-4 py-2 text-right">停損</th>
                <th className="px-4 py-2 text-right">未實現</th>
              </tr>
            </thead>
            <tbody>
              {positions.map(p => {
                const tk = ticks[p.symbol]
                const cur = tk?.price ?? null
                const unreal = cur != null ? (cur - p.entry_price) * p.lots * 1000 : null
                return (
                  <tr key={p.symbol} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                    <td className="px-4 py-2 text-[#60a5fa] font-bold">{p.symbol}</td>
                    <td className="px-4 py-2 text-right text-[#dde6f0]">{p.lots}</td>
                    <td className={`px-4 py-2 text-right ${mono}`}>{p.entry_price?.toFixed(1)}</td>
                    <td className={`px-4 py-2 text-right ${mono} ${cur != null ? chgColor(cur - p.entry_price) : 'text-[#6b84a0]'}`}>{cur != null ? cur.toFixed(1) : '—'}</td>
                    <td className={`px-4 py-2 text-right ${mono} text-orange-400`}>{p.stop_loss?.toFixed(1)}</td>
                    <td className={`px-4 py-2 text-right ${mono} ${unreal != null ? pnlColor(unreal) : 'text-[#6b84a0]'}`}>{unreal != null ? `${unreal >= 0 ? '+' : ''}${unreal.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 日期選擇 */}
      {dates.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs ${muted}`}>選股日期</span>
          {dates.slice(0, 10).map(d => (
            <button
              key={d.date}
              onClick={() => setSelDate(d.date)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                selDate === d.date
                  ? 'bg-[#1e3a5f] text-[#dde6f0] ring-1 ring-[#60a5fa]'
                  : 'bg-[#142035] border border-[#253d5c] text-[#6b84a0] hover:text-[#dde6f0]'
              }`}
            >
              {d.date} <span className="text-[#60a5fa]">({d.count})</span>
            </button>
          ))}
        </div>
      )}

      {/* 選股列表 */}
      <div className={card}>
        <div className="px-4 py-2 border-b border-[#253d5c] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[#dde6f0]">篩選名單</span>
            {list && <Badge text={`${list.count} 檔`} color="blue" />}
            {list?.date && <span className={`text-xs ${muted}`}>{list.date}</span>}
          </div>
        </div>
        {loading ? (
          <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>
        ) : stocks.length === 0 ? (
          <div className={`text-center py-12 text-sm ${muted}`}>無篩選資料</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 text-left">代號　名稱</th>
                  <th className="px-3 py-2 text-right">昨收</th>
                  <th className="px-3 py-2 text-right">現價</th>
                  <th className="px-3 py-2 text-right">漲跌%</th>
                  <th className="px-3 py-2 text-right">均量5</th>
                  <th className="px-3 py-2 text-right">外資</th>
                  <th className="px-3 py-2 text-right">投信</th>
                  <th className="px-3 py-2 text-right">融資</th>
                  <th className="px-3 py-2 text-center">籌碼</th>
                  <th className="px-3 py-2 text-center">MA20</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s: any) => {
                  const tk = ticks[s.stock_id]
                  const livePrice = tk?.price ?? null
                  const ref = s.prev_close
                  const rtChg = livePrice != null && ref ? livePrice - ref : s.change
                  const rtPct = livePrice != null && ref ? rtChg / ref * 100 : s.change_pct
                  const accent = rtChg >= 0 ? 'border-l-green-400' : 'border-l-red-400'
                  const fnet = s.foreign_net as number
                  const tnet = s.trust_net as number
                  const mchg = s.margin_change as number
                  const chips = s.chip_count as number

                  return (
                    <tr key={s.stock_id} className="border-b border-[#253d5c] hover:bg-[#1a2d4a] transition-colors">
                      <td className={`px-3 py-2 border-l-2 ${accent}`}>
                        <span className="font-bold text-[#dde6f0]">{s.stock_id}</span>
                        <span className={`text-xs ml-2 ${muted}`}>{s.name}</span>
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-[#dde6f0]`}>{ref?.toFixed(1)}</td>
                      <td className={`px-3 py-2 text-right ${mono} ${livePrice != null ? chgColor(livePrice - ref) : muted}`}>
                        {livePrice != null ? livePrice.toFixed(1) : '—'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${mono} ${rtPct >= 0 ? 'bg-green-400/15 text-green-400' : 'bg-red-400/15 text-red-400'}`}>
                          {rtPct >= 0 ? '+' : ''}{rtPct.toFixed(2)}%
                        </span>
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-[#dde6f0]`}>
                        {s.avg_vol5 > 0 ? (s.avg_vol5 / 1000).toFixed(0) + 'K' : '—'}
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-xs ${fnet > 0 ? 'text-green-400' : fnet < 0 ? 'text-red-400' : muted}`}>
                        {fnet !== 0 ? `${fnet > 0 ? '+' : ''}${(fnet / 1000).toFixed(0)}K` : '—'}
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-xs ${tnet > 0 ? 'text-green-400' : tnet < 0 ? 'text-red-400' : muted}`}>
                        {tnet !== 0 ? `${tnet > 0 ? '+' : ''}${tnet}` : '—'}
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-xs ${mchg < 0 ? 'text-green-400' : mchg > 0 ? 'text-red-400' : muted}`}>
                        {mchg !== 0 ? `${mchg > 0 ? '+' : ''}${mchg}` : '—'}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`text-xs font-bold ${chips >= 2 ? 'text-green-400' : chips === 1 ? 'text-yellow-400' : muted}`}>
                          {chips}/3
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`text-xs ${s.above_ma20 ? 'text-green-400' : muted}`}>
                          {s.above_ma20 ? '▲' : '▽'}
                        </span>
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

// ── 交易紀錄 ─────────────────────────────────────────────────────────────────
type Period = '本月' | '上月' | '今年' | '全部'

function TradesTab() {
  const [allTrades, setAllTrades] = useState<any[]>([])
  const [period, setPeriod] = useState<Period>('本月')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get(`${API}/trade-history`).then(r => setAllTrades(r.data)).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const filterByPeriod = (rows: any[]) => {
    const now = new Date()
    const y = now.getFullYear(), m = now.getMonth()
    if (period === '本月') {
      const start = `${y}-${String(m + 1).padStart(2, '0')}-01`
      return rows.filter(r => r.trade_date >= start)
    }
    if (period === '上月') {
      const pm = m === 0 ? 12 : m, py = m === 0 ? y - 1 : y
      const start = `${py}-${String(pm).padStart(2, '0')}-01`
      const end = `${y}-${String(m + 1).padStart(2, '0')}-01`
      return rows.filter(r => r.trade_date >= start && r.trade_date < end)
    }
    if (period === '今年') return rows.filter(r => r.trade_date.startsWith(String(y)))
    return rows
  }

  const trades = filterByPeriod(allTrades)
  const totalPnl = trades.reduce((s, r) => s + (r.pnl || 0), 0)
  const totalFee = trades.reduce((s, r) => s + (r.commission || 0), 0)
  const totalNet = totalPnl - totalFee
  const winRows = trades.filter(r => r.pnl > 0).length

  const pnlColor = (v: number) => v > 0 ? 'text-green-400' : v < 0 ? 'text-red-400' : 'text-[#6b84a0]'

  return (
    <div className="space-y-4">
      {/* Period filter */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`text-xs ${muted} mr-1`}>統計期間</span>
        {(['本月', '上月', '今年', '全部'] as Period[]).map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              period === p ? 'bg-[#1e3a5f] text-[#dde6f0] ring-1 ring-[#60a5fa]'
                          : 'bg-[#142035] border border-[#253d5c] text-[#6b84a0] hover:text-[#dde6f0]'
            }`}>{p}</button>
        ))}
      </div>

      {/* Summary */}
      {allTrades.length === 0 && !loading ? (
        <div className={`${card} p-6 text-center`}>
          <div className="text-yellow-400/80 text-sm mb-1">⚠ 尚無實際交易紀錄</div>
          <div className={`text-xs ${muted}`}>系統運行中（DRY RUN 模擬模式）</div>
        </div>
      ) : (
        <div className={`flex flex-wrap gap-px rounded-xl overflow-hidden border border-[#253d5c] bg-[#253d5c]`}>
          {[
            { label: '累計損益', value: `${totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString()}`, color: pnlColor(totalPnl) },
            { label: '實際損益（扣費後）', value: `${totalNet >= 0 ? '+' : ''}${totalNet.toLocaleString()}`, color: pnlColor(totalNet) },
            { label: '手續費合計', value: `-${totalFee.toLocaleString()}`, color: 'text-[#6b84a0]' },
            { label: '筆數', value: trades.length, color: 'text-[#dde6f0]' },
            { label: '獲利筆', value: winRows, color: 'text-green-400' },
          ].map(item => (
            <div key={item.label} className="flex-1 min-w-[100px] bg-[#142035] px-5 py-3 text-center">
              <div className={`text-[10px] uppercase tracking-wider ${muted} mb-1`}>{item.label}</div>
              <div className={`text-xl font-bold ${mono} ${item.color}`}>{item.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Table */}
      <div className={card}>
        <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>明細</div>
        {loading ? (
          <div className={`text-center py-10 text-sm ${muted}`}>載入中...</div>
        ) : trades.length === 0 ? (
          <div className={`text-center py-10 text-sm ${muted}`}>此期間無紀錄</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 text-left">日期</th>
                  <th className="px-3 py-2 text-left">代碼名稱</th>
                  <th className="px-3 py-2 text-right">買價</th>
                  <th className="px-3 py-2 text-right">賣價</th>
                  <th className="px-3 py-2 text-right">損益</th>
                  <th className="px-3 py-2 text-right">手續費</th>
                  <th className="px-3 py-2 text-right">實際損益</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const fee = t.commission || 0
                  const net = (t.pnl || 0) - fee
                  return (
                    <tr key={i} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                      <td className={`px-3 py-2 text-xs ${muted} ${mono}`}>{t.trade_date}</td>
                      <td className="px-3 py-2">
                        <span className="text-[#60a5fa] font-bold">{t.symbol}</span>
                        {t.name && <span className={`text-xs ml-1 ${muted}`}>{t.name}</span>}
                      </td>
                      <td className={`px-3 py-2 text-right ${mono} text-[#dde6f0]`}>{t.avg_entry?.toFixed(1) ?? '—'}</td>
                      <td className={`px-3 py-2 text-right ${mono} text-[#dde6f0]`}>{t.avg_exit?.toFixed(1) ?? '—'}</td>
                      <td className={`px-3 py-2 text-right ${mono} ${pnlColor(t.pnl)}`}>{t.pnl >= 0 ? '+' : ''}{t.pnl?.toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${mono} ${muted}`}>-{fee.toLocaleString()}</td>
                      <td className={`px-3 py-2 text-right ${mono} ${pnlColor(net)}`}>{net >= 0 ? '+' : ''}{net.toLocaleString()}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className={`text-[10px] ${muted}`}>手續費 = 買賣各 0.1425% + 當沖證交稅 0.15%（賣方），各項無條件捨去</div>
    </div>
  )
}

// ── 盤前狀況 ─────────────────────────────────────────────────────────────────
function PreSessionTab() {
  const [logs, setLogs] = useState<any[]>([])
  const [dbSize, setDbSize] = useState(0)

  useEffect(() => {
    axios.get(`${API}/pre-session/logs`).then(r => setLogs(r.data)).catch(() => {})
    axios.get(`${API}/pre-session/db-size`).then(r => setDbSize(r.data.size_mb)).catch(() => {})
  }, [])

  const latest = logs[0]
  const statusColor = (s: string) =>
    s === 'ok' ? 'text-green-400' : s === 'running' ? 'text-yellow-400' : 'text-red-400'
  const statusIcon = (s: string) =>
    s === 'ok' ? '✅' : s === 'running' ? '⏳' : '❌'

  return (
    <div className="space-y-4">
      {/* Top metrics */}
      <div className="grid grid-cols-3 gap-3">
        <MetricCard label="最後執行" value={latest?.run_date ?? '—'} />
        <MetricCard
          label="結果"
          value={latest ? `${statusIcon(latest.status)} ${latest.status === 'ok' ? '成功' : '失敗'}` : '—'}
          color={latest ? statusColor(latest.status) : 'text-[#6b84a0]'}
        />
        <MetricCard
          label="成功／總計"
          value={latest ? `${latest.success_stocks}／${latest.total_stocks}` : '—'}
          color="text-[#dde6f0]"
        />
      </div>
      <MetricCard label="daily.db 大小" value={`${dbSize} MB`} />

      {/* History table */}
      {logs.length > 0 && (
        <div className={card}>
          <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>執行紀錄</div>
          <table className="w-full text-sm">
            <thead>
              <tr className={`text-[11px] ${muted} border-b border-[#253d5c]`}>
                <th className="px-4 py-2 text-left">日期</th>
                <th className="px-4 py-2 text-center">狀態</th>
                <th className="px-4 py-2 text-right">成功</th>
                <th className="px-4 py-2 text-right">總計</th>
                <th className="px-4 py-2 text-left">開始時間</th>
                <th className="px-4 py-2 text-left">結束時間</th>
                <th className="px-4 py-2 text-left">備註</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <tr key={log.id} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                  <td className={`px-4 py-2 ${mono} text-[#dde6f0]`}>{log.run_date}</td>
                  <td className={`px-4 py-2 text-center text-xs font-bold ${statusColor(log.status)}`}>
                    {statusIcon(log.status)} {log.status}
                  </td>
                  <td className="px-4 py-2 text-right text-green-400">{log.success_stocks}</td>
                  <td className="px-4 py-2 text-right text-[#dde6f0]">{log.total_stocks}</td>
                  <td className={`px-4 py-2 text-xs ${muted} ${mono}`}>{log.started_at ?? '—'}</td>
                  <td className={`px-4 py-2 text-xs ${muted} ${mono}`}>{log.finished_at ?? '—'}</td>
                  <td className={`px-4 py-2 text-xs ${log.error_msg ? 'text-red-400' : muted}`}>
                    {log.error_msg ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── 交易設定 ─────────────────────────────────────────────────────────────────
function ParamsTab() {
  const [params, setParams] = useState<any>(null)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  useEffect(() => {
    axios.get(`${API}/trading-params`).then(r => setParams(r.data)).catch(() => {})
  }, [])

  const save = () => {
    setSaving(true)
    axios.post(`${API}/trading-params`, {
      max_position_capital: params.max_position_capital,
      max_daily_positions: params.max_daily_positions,
      dry_run: params.dry_run,
    })
      .then(r => setNote(r.data.note || '已更新'))
      .catch(() => setNote('更新失敗'))
      .finally(() => setSaving(false))
  }

  if (!params) return <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>

  const isDry = params.dry_run
  const modeColor = isDry ? 'text-blue-400' : 'text-red-400'
  const modeLabel = isDry ? '🔵 模擬模式（Dry Run）' : '🔴 實盤模式（LIVE）'

  return (
    <div className="space-y-4 max-w-xl">
      {/* Mode badge */}
      <div className={`${card} px-5 py-3 flex items-center justify-between`}>
        <span className={`text-sm font-bold ${modeColor}`}>{modeLabel}</span>
        <label className="flex items-center gap-2 cursor-pointer">
          <div className="relative">
            <input type="checkbox" className="sr-only" checked={params.dry_run}
              onChange={e => setParams({ ...params, dry_run: e.target.checked })} />
            <div className={`w-10 h-5 rounded-full transition-colors ${params.dry_run ? 'bg-blue-500' : 'bg-red-500'}`} />
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${params.dry_run ? 'left-0.5' : 'left-5.5'}`} />
          </div>
          <span className={`text-sm ${muted}`}>Dry Run</span>
        </label>
      </div>
      {!isDry && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-lg px-4 py-2 text-sm text-red-400">
          ⚠ 關閉 Dry Run 後將進行真實交易，請確認設定
        </div>
      )}

      <div className="space-y-1">
        <SectionLabel>資金設定</SectionLabel>
        <div className={`${card} p-4 space-y-4`}>
          <div>
            <label className={`text-xs ${muted} block mb-1`}>單檔最大資金（TWD）</label>
            <input
              type="number"
              value={params.max_position_capital}
              onChange={e => setParams({ ...params, max_position_capital: +e.target.value })}
              className="w-full bg-[#0c1929] border border-[#253d5c] text-[#dde6f0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#60a5fa]"
            />
          </div>
          <div>
            <label className={`text-xs ${muted} block mb-1`}>每日最多持倉檔數</label>
            <input
              type="number"
              value={params.max_daily_positions}
              onChange={e => setParams({ ...params, max_daily_positions: +e.target.value })}
              className="w-full bg-[#0c1929] border border-[#253d5c] text-[#dde6f0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#60a5fa]"
            />
          </div>
        </div>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="px-6 py-2 bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm rounded-lg font-semibold disabled:opacity-50 hover:shadow-lg hover:shadow-blue-500/30 transition-all"
      >
        {saving ? '儲存中...' : '儲存設定'}
      </button>
      {note && (
        <div className="bg-yellow-900/20 border border-yellow-500/30 rounded-lg px-4 py-2 text-sm text-yellow-400">
          ⚠ {note}
        </div>
      )}
    </div>
  )
}

// ── 系統設定 ─────────────────────────────────────────────────────────────────
function renderConfigSection(title: string, data: Record<string, any>) {
  const entries = Object.entries(data)
  if (entries.length === 0) return null
  return (
    <div key={title} className={`${card} overflow-hidden`}>
      <div className={`px-4 py-2 border-b border-[#253d5c] text-xs font-semibold text-[#60a5fa] uppercase tracking-wider`}>
        {title}
      </div>
      <div className="divide-y divide-[#253d5c]">
        {entries.map(([k, v]) => {
          const isObj = v !== null && typeof v === 'object' && !Array.isArray(v)
          const isArr = Array.isArray(v)
          let display: React.ReactNode
          if (k === 'password' || k === 'cert_password') {
            display = <span className="text-[#6b84a0] italic">***</span>
          } else if (isArr) {
            display = (
              <div className="flex flex-wrap gap-1">
                {v.map((item: any, i: number) => (
                  <span key={i} className="bg-[#0c1929] border border-[#253d5c] rounded px-2 py-0.5 text-xs text-[#dde6f0] font-mono">
                    {typeof item === 'object' ? JSON.stringify(item) : String(item)}
                  </span>
                ))}
              </div>
            )
          } else if (isObj) {
            display = (
              <div className="space-y-0.5">
                {Object.entries(v).map(([sk, sv]) => (
                  <div key={sk} className="flex gap-3">
                    <span className="text-[#6b84a0] font-mono text-xs min-w-[120px]">{sk}</span>
                    <span className="text-[#dde6f0] font-mono text-xs">{JSON.stringify(sv)}</span>
                  </div>
                ))}
              </div>
            )
          } else {
            display = <span className="text-[#dde6f0] font-mono text-sm">{String(v)}</span>
          }
          return (
            <div key={k} className="px-4 py-2.5 grid grid-cols-[180px_1fr] gap-3 items-start">
              <span className="text-xs text-[#6b84a0] font-mono pt-0.5 break-all">{k}</span>
              <div>{display}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConfigTab() {
  const [cfg, setCfg] = useState<any>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    axios.get(`${API}/config`).then(r => setCfg(r.data)).catch(e => setErr(e.message))
  }, [])

  if (err) return <div className="text-red-400 text-sm py-4">{err}</div>
  if (!cfg) return <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>

  const sections: [string, any][] = []
  const SECTION_LABELS: Record<string, string> = {
    fubon: '券商連線設定',
    trading: '交易參數',
    signal: '進場信號',
    position_sizing: '倉位設定',
    risk: '風控設定',
    market_hours: '交易時間',
    circuit_breaker: '熔斷設定',
    data: '資料來源',
  }

  for (const [k, v] of Object.entries(cfg)) {
    if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
      sections.push([SECTION_LABELS[k] ?? k, v as Record<string, any>])
    }
  }

  return (
    <div className="space-y-3">
      <div className="bg-yellow-900/15 border border-yellow-500/25 rounded-lg px-4 py-2 text-xs text-yellow-400/80">
        ⚠ 此頁顯示 config.yaml 唯讀快照，憑證欄位已遮蔽。修改請直接編輯伺服器上的 config.yaml 後重啟引擎。
      </div>
      {sections.map(([title, data]) => renderConfigSection(title, data))}
    </div>
  )
}

// ── 系統健診 ─────────────────────────────────────────────────────────────────
function HealthTab() {
  const [sysStatus, setSysStatus] = useState<any>(null)
  const [apiHealth, setApiHealth] = useState<string | null>(null)
  const [logs, setLogs] = useState<{ lines: string[]; file: string | null; date: string | null }>({ lines: [], file: null, date: null })

  useEffect(() => {
    axios.get(`${API}/health`).then(r => setApiHealth(r.data.status)).catch(() => setApiHealth('error'))
    axios.get(`${API}/system-status`).then(r => setSysStatus(r.data)).catch(() => {})
    axios.get(`${API}/logs/latest?lines=80`).then(r => setLogs({ lines: r.data.lines, file: r.data.file, date: r.data.date })).catch(() => {})
  }, [])

  const st = sysStatus

  type CheckItem = { label: string; value: string | number | null; ok: boolean; note?: string }
  const checks: CheckItem[] = st ? [
    {
      label: 'Dashboard API',
      value: apiHealth === 'ok' ? '🟢 正常' : '🔴 異常',
      ok: apiHealth === 'ok',
    },
    {
      label: 'daily.db',
      value: st.daily_db_mb != null ? `${st.daily_db_mb} MB` : '未掛載',
      ok: (st.daily_db_mb ?? 0) > 0,
    },
    {
      label: 'ticks.db',
      value: st.ticks_db_mb != null ? `${st.ticks_db_mb} MB` : '未掛載',
      ok: (st.ticks_db_mb ?? 0) > 0,
    },
    {
      label: 'Tick 資料量',
      value: st.ticks_count != null ? `${(st.ticks_count as number).toLocaleString()} 筆` : '—',
      ok: (st.ticks_count ?? 0) > 0,
      note: st.last_tick_ts ? `最後：${st.last_tick_ts}` : undefined,
    },
    {
      label: '大盤指數 Tick',
      value: st.index_ticks_count != null ? `${(st.index_ticks_count as number).toLocaleString()} 筆` : '—',
      ok: (st.index_ticks_count ?? 0) > 0,
      note: st.last_index_tick_ts ? `最後：${st.last_index_tick_ts}` : undefined,
    },
    {
      label: '最新篩選日期',
      value: st.daytrade_latest_date ?? '無資料',
      ok: !!st.daytrade_latest_date,
      note: st.daytrade_latest_count != null ? `${st.daytrade_latest_count} 檔` : undefined,
    },
    {
      label: '股票池',
      value: st.watchlist_count != null ? `${st.watchlist_count} 檔` : '—',
      ok: (st.watchlist_count ?? 0) > 0,
    },
    {
      label: '盤前執行',
      value: st.last_presession_date ?? '未執行',
      ok: st.last_presession_status === 'ok',
      note: st.last_presession_status ? `${st.last_presession_status} | ${st.last_presession_success}/${st.last_presession_total}` : undefined,
    },
    {
      label: '今日成交',
      value: st.today_trades != null ? `${st.today_trades} 筆` : '—',
      ok: true,
    },
    {
      label: '最新 Log',
      value: st.latest_log_file ?? '無 log',
      ok: !!st.latest_log_file,
      note: st.latest_log_lines != null ? `${st.latest_log_lines} 行` : undefined,
    },
  ] : []

  return (
    <div className="space-y-4">
      {/* Check table */}
      <div className={card}>
        <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>系統狀態檢查</div>
        {!st ? (
          <div className={`text-center py-10 text-sm ${muted}`}>載入中...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className={`text-[11px] ${muted} border-b border-[#253d5c]`}>
                <th className="px-4 py-2 w-8 text-center">燈</th>
                <th className="px-4 py-2 text-left">項目</th>
                <th className="px-4 py-2 text-left">狀態</th>
                <th className="px-4 py-2 text-left">備註</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((c, i) => (
                <tr key={i} className={`border-b border-[#253d5c] ${c.ok ? '' : 'bg-red-900/5'}`}>
                  <td className="px-4 py-2 text-center text-base">{c.ok ? '✅' : '❌'}</td>
                  <td className={`px-4 py-2 text-xs font-medium ${muted}`}>{c.label}</td>
                  <td className={`px-4 py-2 font-mono text-xs ${c.ok ? 'text-[#dde6f0]' : 'text-red-400'}`}>{c.value}</td>
                  <td className={`px-4 py-2 text-xs ${muted}`}>{c.note ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Log viewer */}
      <div className={card}>
        <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted} flex items-center gap-2`}>
          <span>引擎 Log</span>
          {logs.file && <Badge text={logs.file} />}
          {logs.date && <span className={muted}>{logs.date}</span>}
        </div>
        <div className="p-3 overflow-auto max-h-80">
          {logs.lines.length === 0 ? (
            <div className={`text-xs ${muted}`}>無 log，引擎尚未啟動或尚無記錄</div>
          ) : (
            <pre className={`text-xs ${muted} font-mono leading-4 whitespace-pre-wrap`}>
              {logs.lines.join('\n')}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main page ────────────────────────────────────────────────────────────────
export function DayTradePage() {
  const [sub, setSub] = useState<SubTab>('live')

  return (
    <div className="min-h-screen bg-[#0c1929] text-[#dde6f0] p-6">
      <div className="max-w-6xl mx-auto">
        <div className="mb-5">
          <h1 className="text-2xl font-black text-[#dde6f0]">台股當沖</h1>
          <p className={`text-sm mt-0.5 ${muted}`}>富邦證券自動交易系統</p>
        </div>

        {/* Sub-tab bar */}
        <div className="flex gap-1 mb-6 bg-[#142035] rounded-lg p-1 border border-[#253d5c] w-fit overflow-x-auto">
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setSub(t.id)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap ${
                sub === t.id
                  ? 'bg-[#1e3a5f] text-[#dde6f0] ring-1 ring-[#60a5fa]'
                  : `${muted} hover:text-[#dde6f0] hover:bg-[#1a2d4a]`
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {sub === 'live'        && <LiveTab />}
        {sub === 'trades'      && <TradesTab />}
        {sub === 'pre-session' && <PreSessionTab />}
        {sub === 'params'      && <ParamsTab />}
        {sub === 'config'      && <ConfigTab />}
        {sub === 'health'      && <HealthTab />}
      </div>
    </div>
  )
}
