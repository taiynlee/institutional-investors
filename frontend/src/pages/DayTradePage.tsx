import { type ReactNode, useEffect, useRef, useState } from 'react'
import axios from 'axios'

// ── WebSocket engine stream ───────────────────────────────────────────────────
function useEngineStream() {
  const [data, setData] = useState<any>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/fubon-api/ws/stream`
    let dead = false

    const connect = () => {
      if (dead) return
      const sock = new WebSocket(url)
      wsRef.current = sock
      sock.onmessage = (e) => { try { const d = JSON.parse(e.data); if (!d.ping) setData(d) } catch {} }
      sock.onclose   = () => { if (!dead) setTimeout(connect, 3000) }
      sock.onerror   = () => sock.close()
    }
    connect()
    return () => { dead = true; wsRef.current?.close() }
  }, [])

  return data
}

const API = '/fubon-api'

type SubTab = 'live' | 'trades' | 'pre-session' | 'params' | 'config' | 'health'

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: 'live',        label: '今日交易' },
  { id: 'trades',      label: '交易紀錄' },
  { id: 'pre-session', label: '盤前狀況' },
  { id: 'params',      label: '交易設定' },
  { id: 'config',      label: '當沖設定' },
  { id: 'health',      label: '當沖健診' },
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

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className={`text-[10px] uppercase tracking-[.5px] ${muted} mb-1.5`}>{children}</div>
  )
}

// ── 今日交易 ─────────────────────────────────────────────────────────────────
function LiveTab() {
  const [list, setList] = useState<any | null>(null)
  const [status, setStatus] = useState<{ total_pnl: number; trade_count: number } | null>(null)
  const [positions, setPositions] = useState<any[]>([])
  const [ticks, setTicks] = useState<Record<string, any>>({})
  const [futures, setFutures] = useState<Record<string, any>>({})
  const [engineRunning, setEngineRunning] = useState<boolean | null>(null)
  const evsRef = useRef<EventSource | null>(null)
  const [loading, setLoading] = useState(true)
  const stream = useEngineStream()

  // WebSocket 推送：取代 /status + /positions + /engine/status 輪詢
  useEffect(() => {
    if (!stream) return
    setEngineRunning(stream.status === 'running')
    if (stream.pnl) setStatus({ total_pnl: stream.pnl.actual_pnl ?? 0, trade_count: stream.pnl.actual_trades ?? 0 })
    if (Array.isArray(stream.positions)) setPositions(stream.positions)
  }, [stream])

  useEffect(() => {
    setLoading(true)
    axios.get(`${API}/daytrade-list`)
      .then(r => setList(r.data))
      .catch(() => setList(null))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!list?.stocks?.length) return
    const syms = list.stocks.map((s: any) => s.stock_id).join(',')
    if (evsRef.current) evsRef.current.close()
    const evs = new EventSource(`${API}/stream?syms=${syms}`)
    evs.onmessage = e => { try { setTicks(JSON.parse(e.data)) } catch {} }
    evsRef.current = evs
    return () => evs.close()
  }, [list?.date])

  useEffect(() => {
    if (!list?.stocks?.length) return
    const syms = list.stocks.map((s: any) => s.stock_id).join(',')
    const fetch = () => axios.get(`${API}/futures-snapshot?syms=${syms}`)
      .then(r => { if (r.data?.data) setFutures(r.data.data) }).catch(() => {})
    fetch()
    const tid = setInterval(fetch, 30_000)
    return () => clearInterval(tid)
  }, [list?.date])

  const pnlColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-[#6b84a0]'

  const stocks: any[] = list?.stocks ?? []
  const idxData = ticks['__index__'] ?? {}
  const idxPrice: number | null = idxData.price ?? null
  const idxChg5: number = idxData.chg5 ?? 0
  const circuit: string = idxData.circuit ?? 'normal'
  const isDry = status !== null


  return (
    <div className="space-y-4">
      {/* 6 top metrics row */}
      <div className="grid grid-cols-6 gap-2">
        {/* DRY RUN */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-0.5">模式</span>
          <span className="text-xs font-bold text-blue-400">● DRY RUN 模擬模式</span>
        </div>
        {/* 損益 */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-0.5">損益</span>
          <span className={`text-base font-bold ${mono} ${pnlColor(status?.total_pnl ?? 0)}`}>
            {`${(status?.total_pnl ?? 0) >= 0 ? '+' : ''}${(status?.total_pnl ?? 0).toLocaleString()}`}
          </span>
          <span className={`text-[10px] ${muted}`}>{status?.trade_count ?? 0} 筆</span>
        </div>
        {/* 今日已交易 / 持倉 */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-0.5">今日已交易</span>
          <span className="text-base font-bold text-[#60a5fa]">
            {stream?.pnl?.daily_entries ?? 0}
            <span className="text-[#6b84a0] text-xs font-normal"> / {stream?.pnl?.max_daily ?? 3} 檔</span>
          </span>
          <span className="text-[10px] text-[#6b84a0]">持倉 {positions.length} 檔</span>
        </div>
        {/* 加權指數 */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-0.5">加權指數</span>
          <span className={`text-base font-bold ${mono} text-[#dde6f0]`}>
            {idxPrice != null ? idxPrice.toLocaleString(undefined, {maximumFractionDigits: 0}) : '—'}
          </span>
          <div className="flex items-center gap-1 mt-0.5">
            {idxChg5 !== 0 && <span className={`text-[10px] ${mono} ${idxChg5 >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idxChg5 >= 0 ? '▲' : '▼'}{Math.abs(idxChg5).toFixed(1)}
            </span>}
            <span className={`text-[10px] px-1 py-0.5 rounded ${circuit === 'normal' ? 'bg-green-400/20 text-green-400' : circuit === 'crash' ? 'bg-red-400/20 text-red-400' : 'bg-yellow-400/20 text-yellow-400'}`}>
              {circuit === 'normal' ? '正常' : circuit === 'crash' ? '熔斷' : '急漲'}
            </span>
          </div>
        </div>
        {/* 串流 */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center items-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-1">串流</span>
          <span className={`text-lg ${stream ? 'text-green-400' : 'text-red-400'}`}>●</span>
          <span className={`text-[9px] mt-0.5 ${stream ? 'text-green-400' : 'text-red-400'}`}>{stream ? 'WS已連' : '未連'}</span>
        </div>
        {/* 引擎 */}
        <div className={`${card} px-3 py-3 flex flex-col justify-center items-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-1">引擎</span>
          <span className={`text-lg ${engineRunning === true ? 'text-green-400' : engineRunning === false ? 'text-red-400' : muted}`}>●</span>
          <span className={`text-[9px] mt-0.5 ${engineRunning === true ? 'text-green-400' : engineRunning === false ? 'text-red-400' : muted}`}>
            {stream?.status ?? '偵測中'}
          </span>
        </div>
      </div>

      {/* 持倉明細 */}
      {positions.length > 0 && (
        <div className={card}>
          <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>▸ 持倉 ({positions.length})</div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[700px]">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c]`}>
                  <th className="px-4 py-2 text-left">代號</th>
                  <th className="px-4 py-2 text-right">張</th>
                  <th className="px-4 py-2 text-right">成本</th>
                  <th className="px-4 py-2 text-right">現價</th>
                  <th className="px-4 py-2 text-right">停損線</th>
                  <th className="px-4 py-2 text-right">ATR</th>

                  <th className="px-4 py-2 text-right">未實現</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(p => {
                  const tk = ticks[p.symbol]
                  const cur = tk?.price ?? null
                  const unreal = cur != null ? (cur - p.entry_price) * p.lots * 1000 : null
                  const uc = unreal != null ? (unreal >= 0 ? 'text-red-400' : 'text-green-400') : muted
                  const nearStop = cur != null && p.stop_loss != null && cur <= p.stop_loss * 1.02
                  return (
                    <tr key={p.symbol} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                      <td className="px-4 py-2 text-[#60a5fa] font-bold">{p.symbol}</td>
                      <td className="px-4 py-2 text-right text-[#dde6f0]">{p.lots}</td>
                      <td className={`px-4 py-2 text-right ${mono} text-[#dde6f0]`}>{p.entry_price?.toFixed(1)}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${cur != null ? (cur >= p.entry_price ? 'text-red-400' : 'text-green-400') : muted}`}>{cur != null ? cur.toFixed(1) : '—'}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${nearStop ? 'text-red-400 font-bold' : 'text-orange-400'}`}>{p.stop_loss?.toFixed(1) ?? '—'}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${muted}`}>{p.atr != null ? p.atr.toFixed(2) : '—'}</td>

                      <td className={`px-4 py-2 text-right ${mono} ${uc}`}>{unreal != null ? `${unreal >= 0 ? '+' : ''}${Math.round(unreal).toLocaleString()}` : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 主列表：照 Fubon 欄位 */}
      <div className={card}>
        {/* 列表標頭 */}
        <div className="px-4 py-2 border-b border-[#253d5c] flex items-center gap-2">
          <span className="text-sm font-semibold text-[#dde6f0]">明日選股</span>
          {list && <Badge text={`${list.count} 檔`} color="blue" />}
          {list?.date && <span className={`text-xs ${muted}`}>{list.date}</span>}
        </div>

        {loading ? (
          <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>
        ) : stocks.length === 0 ? (
          <div className={`text-center py-12 text-sm ${muted}`}>無篩選資料</div>
        ) : (
          <div>
            <table className="w-full text-sm">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 text-left" style={{minWidth:150}}>代碼　名稱</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:52}}>昨收</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:60}}>現價</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>漲跌</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:66}}>漲跌%</th>
                  <th className="px-3 py-2 text-left"  style={{minWidth:104}}>買賣盤</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>期貨</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:50}}>差價</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>Open</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>High</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>Low</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:72}}>今量</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s: any) => {
                  const tk = ticks[s.stock_id] ?? {}
                  const lp    = tk.price ?? null
                  const ref   = s.prev_close
                  const rtChg = lp != null && ref ? lp - ref : s.change
                  const rtPct = lp != null && ref ? rtChg / ref * 100 : s.change_pct
                  const isUp  = rtChg >= 0
                  const accent = isUp ? 'border-l-red-400' : 'border-l-green-400'
                  const chgCls = isUp ? 'text-red-400' : 'text-green-400'

                  const bp     = tk.bid_pct ?? null
                  const ap     = bp != null ? 100 - bp : null
                  const bidStr = bp != null && bp >= 65

                  const open_v  = tk.open      ?? null
                  const high_v  = tk.high      ?? null
                  const low_v   = tk.low       ?? null
                  const vol     = tk.vol_lots  ?? null
                  const v1m     = tk.vol_1m    ?? null
                  const vpm     = tk.vol_prev_1m ?? null
                  const volRise = v1m != null && vpm != null && v1m > vpm

                  const dash = <span className={muted}>—</span>

                  return (
                    <tr key={s.stock_id} className="border-b border-[#253d5c] hover:bg-[#1a2d4a] transition-colors">
                      {/* 代碼名稱 */}
                      <td className={`px-3 py-2.5 border-l-2 ${accent}`}>
                        <span className="font-bold text-[14px] text-[#dde6f0]">{s.stock_id}</span>
                        <span className={`text-xs ml-1.5 ${muted}`}>{s.name}</span>
                      </td>
                      {/* 昨收 */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs text-[#dde6f0]`}>{ref?.toFixed(1)}</td>
                      {/* 現價 */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-sm font-bold ${lp != null ? chgCls : muted}`}>
                        {lp != null ? lp.toFixed(1) : '—'}
                      </td>
                      {/* 漲跌 (絕對值) */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs ${chgCls}`}>
                        {`${isUp ? '+' : ''}${rtChg.toFixed(1)}`}
                      </td>
                      {/* 漲跌% */}
                      <td className="px-3 py-2.5 text-right">
                        <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold ${mono} ${isUp ? 'bg-red-400/15 text-red-400' : 'bg-green-400/15 text-green-400'}`}>
                          {`${isUp ? '+' : ''}${rtPct.toFixed(2)}%`}
                        </span>
                      </td>
                      {/* 買賣盤 — 委買 ≥ 65% 亮訊號 */}
                      <td className="px-3 py-2.5">
                        {bp != null ? (
                          <div>
                            <div className={`flex h-[5px] rounded overflow-hidden mb-0.5 ${bidStr ? 'ring-1 ring-red-400/60' : ''}`} style={{width:86}}>
                              <div className="bg-red-400" style={{width:`${bp}%`}} />
                              <div className="bg-green-400" style={{width:`${ap}%`}} />
                            </div>
                            <div className={`flex items-center justify-between text-[10px] ${mono}`} style={{width:86}}>
                              <span className={bidStr ? 'text-red-400 font-bold' : 'text-red-300'}>
                                買{bp.toFixed(0)}%{bidStr ? '▲' : ''}
                              </span>
                              <span className="text-green-400">賣{ap?.toFixed(0)}%</span>
                            </div>
                          </div>
                        ) : dash}
                      </td>
                      {/* 期貨 */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs`}>
                        {futures[s.stock_id] ? (
                          <span className={futures[s.stock_id].change >= 0 ? 'text-red-400' : 'text-green-400'}>
                            {futures[s.stock_id].price.toFixed(0)}
                          </span>
                        ) : <span className={muted}>—</span>}
                      </td>
                      {/* 差價 */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs`}>
                        {futures[s.stock_id] && lp != null ? (() => {
                          const sp = futures[s.stock_id].price - lp
                          return <span className={sp >= 0 ? 'text-red-400' : 'text-green-400'}>{sp > 0 ? '+' : ''}{sp.toFixed(1)}</span>
                        })() : <span className={muted}>—</span>}
                      </td>
                      {/* Open */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs text-[#dde6f0]`}>
                        {open_v != null ? open_v.toFixed(1) : '—'}
                      </td>
                      {/* High */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs text-red-400`}>
                        {high_v != null ? high_v.toFixed(1) : '—'}
                      </td>
                      {/* Low */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs text-green-400`}>
                        {low_v != null ? low_v.toFixed(1) : '—'}
                      </td>
                      {/* 今量 ratio bar */}
                      <td className="px-3 py-2.5">
                        {vol != null ? (() => {
                          const ratio = s.avg_vol5 > 0 ? vol / s.avg_vol5 : null
                          const barW  = ratio != null ? Math.min(ratio * 100, 100) : 0
                          const barCl = ratio == null ? 'bg-[#6b84a0]' : ratio >= 1.2 ? 'bg-green-400' : ratio >= 0.5 ? 'bg-yellow-400' : 'bg-[#6b84a0]'
                          const txtCl = ratio == null ? muted : ratio >= 1.2 ? 'text-green-400' : ratio >= 0.5 ? 'text-yellow-400' : muted
                          return (
                            <div style={{width:92}}>
                              <div className="h-[4px] rounded mb-1 bg-[#253d5c]">
                                <div className={`h-full rounded ${barCl}`} style={{width:`${barW}%`}} />
                              </div>
                              <div className={`flex items-center gap-1 text-[10px] ${mono}`}>
                                <span className={txtCl}>{vol >= 1000 ? `${Math.floor(vol/1000)}K` : vol}張</span>
                                <span className={muted}>│</span>
                                <span className={muted}>avg {s.avg_vol5 >= 1000 ? `${Math.round(s.avg_vol5/1000)}K` : s.avg_vol5}</span>
                              </div>
                            </div>
                          )
                        })() : <span className={muted}>—</span>}
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
type Period = '今日' | '本月' | '上一月' | '上二月' | '上三月' | '今年' | '全部'


function TradesTab() {
  const [allTrades, setAllTrades] = useState<any[]>([])
  const [period, setPeriod] = useState<Period>('今日')
  const [loading, setLoading] = useState(true)
  const [deleting, setDeleting] = useState<string | null>(null)

  const loadTrades = () => {
    setLoading(true)
    axios.get(`${API}/trade-history`).then(r => setAllTrades(r.data)).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => { loadTrades() }, [])

  const deleteTrade = async (trade_date: string, symbol: string) => {
    const key = `${trade_date}-${symbol}`
    setDeleting(key)
    try {
      await axios.delete(`${API}/delete-trade`, { params: { trade_date, symbol } })
      loadTrades()
    } catch { }
    setDeleting(null)
  }

  const filterByPeriod = (rows: any[]) => {
    const now = new Date()
    const y = now.getFullYear(), m = now.getMonth()
    const todayStr = `${y}-${String(m+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`
    const monthStart = (offset: number) => {
      const d = new Date(y, m - offset, 1)
      return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`
    }
    const monthEnd = (offset: number) => {
      const d = new Date(y, m - offset + 1, 1)
      return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-01`
    }
    if (period === '今日')   return rows.filter(r => r.trade_date === todayStr)
    if (period === '本月')   return rows.filter(r => r.trade_date >= monthStart(0))
    if (period === '上一月') return rows.filter(r => r.trade_date >= monthStart(1) && r.trade_date < monthEnd(1))
    if (period === '上二月') return rows.filter(r => r.trade_date >= monthStart(2) && r.trade_date < monthEnd(2))
    if (period === '上三月') return rows.filter(r => r.trade_date >= monthStart(3) && r.trade_date < monthEnd(3))
    if (period === '今年')   return rows.filter(r => r.trade_date.startsWith(String(y)))
    return rows
  }

  const activeTrades = allTrades
  const trades = filterByPeriod(activeTrades)
  const totalPnl = trades.reduce((s, r) => s + (r.pnl || 0), 0)
  const totalFee = trades.reduce((s, r) => s + (r.commission || 0), 0)
  const totalNet = totalPnl - totalFee
  const totalRebate = trades.reduce((s, r) => s + Math.floor((r.brokerage_only || 0) * 0.72), 0)
  const winRows = trades.filter(r => (r.pnl || 0) - (r.commission || 0) > 0).length
  const winRate = trades.length > 0 ? Math.round(winRows / trades.length * 100) : 0

  const pnlColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-[#6b84a0]'

  return (
    <div className="space-y-4">
      {/* Period filter */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className={`text-xs ${muted} mr-1`}>統計期間</span>
        {(['今日', '本月', '上一月', '上二月', '上三月', '今年', '全部'] as Period[]).map(p => (
          <button key={p} onClick={() => setPeriod(p)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              period === p ? 'bg-[#1e3a5f] text-[#dde6f0] ring-1 ring-[#60a5fa]'
                          : 'bg-[#142035] border border-[#253d5c] text-[#6b84a0] hover:text-[#dde6f0]'
            }`}>{p}</button>
        ))}
      </div>

      {/* Summary */}
      {activeTrades.length === 0 && !loading ? (
        <div className={`${card} p-6 text-center`}>
          <div className="text-yellow-400/80 text-sm mb-1">⚠ 尚無實際交易紀錄</div>
          <div className={`text-xs ${muted}`}>系統運行中（DRY RUN 模擬模式）</div>
        </div>
      ) : (
        <div className={`flex flex-wrap gap-px rounded-xl overflow-hidden border border-[#253d5c] bg-[#253d5c]`}>
          {[
            { label: '累計損益',       value: `${totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString()}`,   color: pnlColor(totalPnl) },
            { label: '累計實際損益',   value: `${totalNet >= 0 ? '+' : ''}${totalNet.toLocaleString()}`,   color: pnlColor(totalNet) },
            { label: '交易手續費合計', value: `-${totalFee.toLocaleString()}`,                              color: muted },
            { label: '預估月退讓',     value: `+${totalRebate.toLocaleString()}`,                          color: 'text-blue-400' },
            { label: '筆數',           value: String(trades.length),                                        color: 'text-[#dde6f0]' },
            { label: '獲利率',         value: `${winRate}%`,                                               color: winRate >= 50 ? 'text-red-400' : 'text-green-400' },
          ].map(item => (
            <div key={item.label} className="flex-1 min-w-[90px] bg-[#142035] px-4 py-3 text-center">
              <div className={`text-[10px] ${muted} mb-1`}>{item.label}</div>
              <div className={`text-lg font-bold ${mono} ${item.color}`}>{item.value}</div>
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
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 text-left">日期</th>
                  <th className="px-3 py-2 text-left">模式</th>
                  <th className="px-3 py-2 text-left">代碼名稱</th>
                  <th className="px-3 py-2 text-right">張數</th>
                  <th className="px-3 py-2 text-right">總買額</th>
                  <th className="px-3 py-2 text-right">買價</th>
                  <th className="px-3 py-2 text-right">賣價</th>
                  <th className="px-3 py-2 text-right">損益</th>
                  <th className="px-3 py-2 text-right">交易手續費</th>
                  <th className="px-3 py-2 text-right">實際損益</th>
                  <th className="px-3 py-2 text-right">券商退讓</th>
                  <th className="px-3 py-2 text-center w-8"></th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const fee = t.commission || 0
                  const net = (t.pnl || 0) - fee
                  const rebate = Math.floor((t.brokerage_only || 0) * 0.72)
                  const lots = t.total_lots ?? t.trade_count ?? 1
                  const totalBuy = t.avg_entry != null ? Math.round(t.avg_entry * lots * 1000) : null
                  const delKey = `${t.trade_date}-${t.symbol}`
                  return (
                    <tr key={i} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                      <td className={`px-3 py-2.5 text-xs ${muted} ${mono}`}>{t.trade_date}</td>
                      <td className="px-3 py-2.5">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${t.dry_run ? 'bg-blue-900/40 text-blue-300' : 'bg-red-900/40 text-red-300'}`}>
                          ● {t.dry_run ? 'DRY' : 'LIVE'}
                        </span>
                      </td>
                      <td className="px-3 py-2.5">
                        <span className={`${mono} text-[#60a5fa] font-bold`}>{t.symbol}</span>
                        {t.name && <span className={`text-xs ml-1.5 text-[#dde6f0]`}>{t.name}</span>}
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-[#dde6f0]`}>{lots} 張</td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-[#dde6f0]`}>
                        {totalBuy != null ? totalBuy.toLocaleString() : '—'}
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-[#dde6f0]`}>{t.avg_entry?.toFixed(1) ?? '—'}</td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-[#dde6f0]`}>{t.avg_exit?.toFixed(1) ?? '—'}</td>
                      <td className={`px-3 py-2.5 text-right ${mono} ${pnlColor(t.pnl)}`}>{t.pnl >= 0 ? '+' : ''}{t.pnl?.toLocaleString()}</td>
                      <td className={`px-3 py-2.5 text-right ${mono} ${muted}`}>-{fee.toLocaleString()}</td>
                      <td className={`px-3 py-2.5 text-right ${mono} ${pnlColor(net)}`}>{net >= 0 ? '+' : ''}{net.toLocaleString()}</td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-blue-400`}>+{rebate.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-center">
                        <button
                          onClick={() => deleteTrade(t.trade_date, t.symbol)}
                          disabled={deleting === delKey}
                          className="text-[11px] text-[#6b84a0] hover:text-red-400 transition-colors disabled:opacity-40"
                          title="刪除"
                        >✕</button>
                      </td>
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
  const [logs, setLogs]         = useState<any[]>([])
  const [dates, setDates]       = useState<{ date: string; count: number }[]>([])
  const [selDate, setSelDate]   = useState('')
  const [list, setList]         = useState<any | null>(null)
  const [listLoading, setListLoading] = useState(false)

  useEffect(() => {
    axios.get(`${API}/pre-session/logs`).then(r => setLogs(r.data)).catch(() => {})
    axios.get(`${API}/daytrade-list/dates`).then(r => {
      setDates(r.data)
      if (r.data.length > 0) setSelDate(r.data[0].date)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selDate) return
    setListLoading(true)
    axios.get(`${API}/daytrade-list?date_str=${selDate}`)
      .then(r => setList(r.data))
      .catch(() => setList(null))
      .finally(() => setListLoading(false))
  }, [selDate])

  const latest = logs[0]
  const stocks: any[] = list?.stocks ?? []

  const ck  = (v: boolean) => v
    ? <span className="text-green-400 font-bold text-xs">✔</span>
    : <span className="text-red-400 font-bold text-xs">✘</span>
  const chip = (v: boolean) => v
    ? <span className="text-green-400 text-xs">●</span>
    : <span className={`${muted} text-xs`}>○</span>

  return (
    <div className="space-y-4">
      {/* 盤前批次摘要 */}
      {latest && (
        <div className={`${card} px-4 py-3 flex items-center gap-6`}>
          <div>
            <div className={`text-[10px] ${muted}`}>最後執行</div>
            <div className={`${mono} text-sm text-[#dde6f0]`}>{latest.run_date}</div>
          </div>
          <div>
            <div className={`text-[10px] ${muted}`}>結果</div>
            <div className={`text-sm font-bold ${latest.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
              {latest.status === 'ok' ? '✔ 成功' : '✘ 失敗'}
            </div>
          </div>
          <div>
            <div className={`text-[10px] ${muted}`}>成功 / 總計</div>
            <div className={`${mono} text-sm text-[#dde6f0]`}>{latest.success_stocks} / {latest.total_stocks}</div>
          </div>
          {latest.finished_at && (
            <div>
              <div className={`text-[10px] ${muted}`}>完成時間</div>
              <div className={`${mono} text-xs text-[#dde6f0]`}>{latest.finished_at}</div>
            </div>
          )}
          {latest.error_msg && (
            <div className="flex-1">
              <div className={`text-[10px] ${muted}`}>錯誤</div>
              <div className="text-xs text-red-400">{latest.error_msg}</div>
            </div>
          )}
        </div>
      )}

      {/* 篩選條件說明 */}
      <div className={`${card} px-4 py-3`}>
        <div className={`text-[10px] uppercase tracking-widest ${muted} mb-2`}>每日選股規則</div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-xs text-[#dde6f0]">
          <div className="font-semibold text-[#60a5fa] mb-0.5">必要條件（3條全過）</div>
          <div className="font-semibold text-[#60a5fa] mb-0.5">籌碼加分（≥ 2條入選）</div>
          <div>✔ 在 TWSE 當沖標的名單</div>
          <div>⬡ 外資昨日買超（foreign_net &gt; 0）</div>
          <div>✔ 近5日均量 ≥ 2000張（avg_vol5）</div>
          <div>⬡ 投信連續買超（trust_net &gt; 0）</div>
          <div>✔ 收盤價 &gt; MA20（日線）</div>
          <div>⬡ 融資餘額日減少（margin_change &lt; 0）</div>
        </div>
      </div>


      {/* 篩選名單 per-stock 條件表 */}
      <div className={card}>
        <div className={`px-4 py-2 border-b border-[#253d5c] flex items-center gap-2`}>
          <span className={`text-xs ${muted}`}>選股結果</span>
          {list && <Badge text={`${list.count} 檔`} color="blue" />}
          {list?.date && <span className={`text-xs ${muted}`}>{list.date}</span>}
        </div>
        {listLoading ? (
          <div className={`text-center py-10 text-sm ${muted}`}>載入中...</div>
        ) : stocks.length === 0 ? (
          <div className={`text-center py-10 text-sm ${muted}`}>無資料</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 text-left">代碼名稱</th>
                  <th className="px-3 py-2 text-right">昨收</th>
                  <th className="px-3 py-2 text-right">均量5日</th>
                  <th className="px-3 py-2 text-center">MA20</th>
                  <th className="px-3 py-2 text-center">外資</th>
                  <th className="px-3 py-2 text-center">投信</th>
                  <th className="px-3 py-2 text-center">融資↓</th>
                  <th className="px-3 py-2 text-center">籌碼分</th>
                  <th className="px-3 py-2 text-right">外資淨</th>
                  <th className="px-3 py-2 text-right">投信淨</th>
                  <th className="px-3 py-2 text-right">融資增</th>
                </tr>
              </thead>
              <tbody>
                {stocks.map((s: any) => {
                  const volOk  = s.vol_ok
                  const ma20Ok = s.above_ma20
                  const forOk  = (s.foreign_net ?? 0) > 0
                  const truOk  = (s.trust_net ?? 0) > 0
                  const mgnOk  = (s.margin_change ?? 0) < 0
                  const chipCnt = (forOk ? 1 : 0) + (truOk ? 1 : 0) + (mgnOk ? 1 : 0)
                  const chipPass = chipCnt >= 2
                  return (
                    <tr key={s.stock_id} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                      <td className="px-3 py-2.5">
                        <span className={`${mono} font-bold text-[#60a5fa]`}>{s.stock_id}</span>
                        <span className={`text-xs ml-1.5 text-[#dde6f0]`}>{s.name}</span>
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs text-[#dde6f0]`}>
                        {s.prev_close?.toFixed(1) ?? '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <span className={`text-xs ${mono} ${volOk ? 'text-green-400' : 'text-red-400'}`}>
                          {s.avg_vol5 >= 1000 ? `${Math.round(s.avg_vol5/1000)}K` : Math.round(s.avg_vol5 ?? 0)}張
                        </span>
                        {!volOk && <span className="ml-1 text-[10px] text-red-400">✘</span>}
                      </td>
                      <td className="px-3 py-2.5 text-center">{ck(ma20Ok)}</td>
                      <td className="px-3 py-2.5 text-center">{chip(forOk)}</td>
                      <td className="px-3 py-2.5 text-center">{chip(truOk)}</td>
                      <td className="px-3 py-2.5 text-center">{chip(mgnOk)}</td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${chipPass ? 'bg-green-400/15 text-green-400' : 'bg-[#253d5c] text-[#6b84a0]'}`}>
                          {chipCnt}/3
                        </span>
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs ${forOk ? 'text-green-400' : 'text-red-400'}`}>
                        {s.foreign_net > 0 ? '+' : ''}{s.foreign_net?.toLocaleString() ?? '—'}
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs ${truOk ? 'text-green-400' : 'text-red-400'}`}>
                        {s.trust_net > 0 ? '+' : ''}{s.trust_net?.toLocaleString() ?? '—'}
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs ${mgnOk ? 'text-green-400' : 'text-[#dde6f0]'}`}>
                        {s.margin_change > 0 ? '+' : ''}{s.margin_change?.toLocaleString() ?? '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 歷史執行紀錄（折疊摘要） */}
      {logs.length > 1 && (
        <div className={card}>
          <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted}`}>執行紀錄（最近{logs.length}次）</div>
          <table className="w-full text-xs">
            <tbody>
              {logs.map(log => (
                <tr key={log.id} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                  <td className={`px-4 py-1.5 ${mono} text-[#dde6f0]`}>{log.run_date}</td>
                  <td className={`px-4 py-1.5 font-bold ${log.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>{log.status}</td>
                  <td className={`px-4 py-1.5 ${muted}`}>{log.success_stocks}/{log.total_stocks}</td>
                  <td className={`px-4 py-1.5 ${mono} ${muted}`}>{log.started_at ?? '—'}</td>
                  <td className={`px-4 py-1.5 text-red-400`}>{log.error_msg ?? ''}</td>
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
interface PD { id: string; group: string; label: string; desc: string; unit: string; source: 'rt'|'cfg'; rtKey?: string; cfgPath?: string; type: 'number'|'time'; step?: number; min?: number; max?: number; canDisable: boolean }
const PARAM_DEFS: PD[] = [
  // 倉位控制
  { id:'max_position_capital', group:'倉位控制', label:'每檔資金上限',   desc:'單一標的最多動用的資金；ATR 張數算完後再 cap 到此值', unit:'TWD', source:'rt', rtKey:'max_position_capital', type:'number', step:100000, min:100000, canDisable:false },
  { id:'max_daily_positions',  group:'倉位控制', label:'每日最多交易檔數', desc:'一天最多買賣幾檔股票；進場後即使出場也計入，達上限後當日不再開新倉', unit:'檔', source:'rt', rtKey:'max_daily_positions', type:'number', step:1, min:1, canDisable:false },
  { id:'risk_per_trade_pct',   group:'倉位控制', label:'每筆風險比例',   desc:'每筆交易最多承擔總資金×此%的風險，決定張數公式基數', unit:'%', source:'cfg', cfgPath:'risk.risk_per_trade_pct', type:'number', step:0.5, min:0.1, canDisable:false },
  // 交易時間
  { id:'force_exit_time',          group:'交易時間', label:'強制出場時間',  desc:'到達此時間所有持倉強制市價出清，不管盈虧', unit:'HH:MM', source:'cfg', cfgPath:'trading.force_exit_time', type:'time', canDisable:false },
  { id:'latest_dynamic_add_time',  group:'交易時間', label:'動態加入截止',  desc:'此時間後不接受新進場信號，距收盤太近避免來不及出清', unit:'HH:MM', source:'cfg', cfgPath:'trading.latest_dynamic_add_time', type:'time', canDisable:false },
  { id:'time_stop_hour',           group:'交易時間', label:'時間止損',  desc:'持倉超過此時間仍虧損（price < entry）→ 自動出場（12.5 = 12:30）', unit:'時', source:'cfg', cfgPath:'trading.time_stop_hour', type:'number', step:0.5, min:9, max:13.5, canDisable:false },
  // 大盤熔斷
  { id:'cb_crash_pct',      group:'大盤熔斷', label:'急跌熔斷門檻',  desc:'觀察視窗內大盤跌幅超過此% → 出清全倉並暫停進場；同比例急漲視為 surge 狀態', unit:'%', source:'rt', rtKey:'cb_crash_pct', type:'number', step:0.5, min:0.5, canDisable:true },
  { id:'cb_window_min',     group:'大盤熔斷', label:'熔斷觀察視窗',  desc:'計算急跌的時間視窗（分鐘）', unit:'分鐘', source:'rt', rtKey:'cb_window_min', type:'number', step:1, min:1, canDisable:false },
  { id:'cb_pause_minutes',  group:'大盤熔斷', label:'熔斷暫停時間',  desc:'觸發熔斷後暫停新開倉的分鐘數（即時生效）', unit:'分鐘', source:'rt', rtKey:'cb_pause_minutes', type:'number', step:5, min:5, canDisable:false },
  // 進場信號
  { id:'market_drop_threshold', group:'進場信號', label:'大盤日跌門檻',      desc:'加權今日較昨收跌超過此%時停止新開倉（例：-1.5 = 跌1.5%停買）', unit:'%', source:'cfg', cfgPath:'signal.market_drop_threshold', type:'number', step:0.5, canDisable:true },
  { id:'max_entry_gain_pct',    group:'進場信號', label:'最大進場漲幅',      desc:'個股當日漲幅超過此%不開倉，避免追高；ORB 突破時本條件仍生效', unit:'%', source:'cfg', cfgPath:'signal.max_entry_gain_pct', type:'number', step:0.5, min:0, canDisable:true },
  { id:'limit_up_buffer',       group:'進場信號', label:'漲停緩衝',          desc:'股價距漲停不足此%時不進場，避免追板買在最高點', unit:'%', source:'cfg', cfgPath:'signal.limit_up_buffer', type:'number', step:0.5, min:0, canDisable:true },
  // 期貨過濾
  { id:'futures_rocket_threshold',         group:'期貨過濾', label:'期貨急漲門檻',   desc:'個股期貨漲幅超過此% → 視為強勢標的，取消正常停利等漲停賣', unit:'%', source:'cfg', cfgPath:'signal.futures_rocket_threshold', type:'number', step:0.5, min:0, canDisable:true },
  { id:'futures_crash_threshold',          group:'期貨過濾', label:'期貨急跌門檻',   desc:'個股期貨跌幅超過此% → 視為崩跌，立即市價出清', unit:'%', source:'cfg', cfgPath:'signal.futures_crash_threshold', type:'number', step:0.5, min:0, canDisable:true },
  { id:'futures_spread_no_buy_pct',        group:'期貨過濾', label:'逆價差—禁止買',  desc:'期現差呈逆差超過此%時不開新倉（期貨端空方壓力警示）', unit:'%', source:'cfg', cfgPath:'signal.futures_spread_no_buy_pct', type:'number', step:0.1, min:0, canDisable:true },
  { id:'futures_spread_reduce_pct',        group:'期貨過濾', label:'逆價差—減半倉',  desc:'逆差超過此%時，計算張數後減半，控制暴露風險', unit:'%', source:'cfg', cfgPath:'signal.futures_spread_reduce_pct', type:'number', step:0.1, min:0, canDisable:true },
  { id:'futures_spread_sell_pct',          group:'期貨過濾', label:'逆價差—立即賣',  desc:'逆差超過此%時，持倉全數立即出清', unit:'%', source:'cfg', cfgPath:'signal.futures_spread_sell_pct', type:'number', step:0.5, min:0, canDisable:true },
  { id:'futures_spread_fast_reversal_pct', group:'期貨過濾', label:'逆價差急惡化',   desc:'短窗口內逆差擴大速度超過此值時加速出場（趨勢惡化預警）', unit:'%', source:'cfg', cfgPath:'signal.futures_spread_fast_reversal_pct', type:'number', step:0.1, min:0, canDisable:true },
  // 風控
  { id:'atr_multiplier',         group:'風控', label:'ATR 倍數',       desc:'停損距離 = ATR × 此倍數；同時決定張數公式分母（資金×1% ÷ (ATR×倍數×1000)）', unit:'x', source:'cfg', cfgPath:'risk.atr_multiplier', type:'number', step:0.5, min:0.5, canDisable:false },
  // 停利/停損策略
  { id:'take_profit_pct',       group:'停利策略', label:'最終停利',          desc:'漲幅達此%時全部出清', unit:'%', source:'cfg', cfgPath:'risk.take_profit_pct', type:'number', step:0.5, min:0, canDisable:true },
  { id:'trailing_trigger_pct',  group:'停利策略', label:'移動停損啟動',      desc:'獲利達此%後啟動移動停損追蹤；之後從最高點回落 trailing_pullback_pct% 即出場', unit:'%', source:'cfg', cfgPath:'risk.trailing_trigger_pct', type:'number', step:0.5, min:0.5, canDisable:false },
  { id:'trailing_pullback_pct', group:'停利策略', label:'移動停損回落幅度',  desc:'啟動移動停損後，從歷史最高點回落此%即觸發出場', unit:'%', source:'cfg', cfgPath:'risk.trailing_pullback_pct', type:'number', step:0.5, min:0.5, canDisable:false },
  // 委託設定
  { id:'buy_order_timeout_secs',     group:'委託設定', label:'買單逾時',      desc:'買單掛出後超過此秒數未成交，自動取消並追價重試（dry run 無效）', unit:'秒', source:'cfg', cfgPath:'order.buy_order_timeout_secs', type:'number', step:10, min:10, canDisable:false },
  { id:'buy_retry_ticks',            group:'委託設定', label:'追價 tick 數',  desc:'追價委託時在最新成交價上加幾個 tick，避免又追不到（dry run 無效）', unit:'tick', source:'cfg', cfgPath:'order.buy_retry_ticks', type:'number', step:1, min:0, canDisable:false },
  { id:'commission_discount',        group:'委託設定', label:'手續費折扣',    desc:'券商手續費折讓倍率：0.28 = 付28%，72% 月底退還', unit:'折', source:'rt', rtKey:'commission_discount', type:'number', step:0.01, min:0.01, max:1, canDisable:false },
  { id:'futures_poll_interval_secs', group:'委託設定', label:'期貨輪詢間隔',  desc:'主動查詢個股期貨價格的間隔秒數（REST API，非 WebSocket）', unit:'秒', source:'cfg', cfgPath:'order.futures_poll_interval_secs', type:'number', step:5, min:5, canDisable:false },
]

const _PARAM_GROUPS = Array.from(new Set(PARAM_DEFS.map(p => p.group)))

function getCfgVal(cfg: any, dotted: string): any {
  const parts = dotted.split('.')
  let v: any = cfg
  for (const p of parts) v = v?.[p]
  return v
}

function ParamsTab() {
  const [rtParams, setRtParams] = useState<any>(null)
  const [cfgData,  setCfgData]  = useState<any>(null)
  const [vals, setVals] = useState<Record<string, any>>({})
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() => {
    try { const s = localStorage.getItem('fubon_param_enabled'); if (s) return JSON.parse(s) } catch {}
    return Object.fromEntries(PARAM_DEFS.map(p => [p.id, true]))
  })
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<{ok: boolean; msg: string} | null>(null)

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/trading-params`),
      axios.get(`${API}/config`),
    ]).then(([r1, r2]) => {
      setRtParams(r1.data)
      setCfgData(r2.data)
      const v: Record<string, any> = {}
      for (const p of PARAM_DEFS) {
        v[p.id] = p.source === 'rt'
          ? r1.data[p.rtKey!]
          : getCfgVal(r2.data, p.cfgPath!)
      }
      setVals(v)
    }).catch(() => {})
  }, [])

  const toggle = (id: string) => setEnabled(prev => {
    const next = { ...prev, [id]: !prev[id] }
    try { localStorage.setItem('fubon_param_enabled', JSON.stringify(next)) } catch {}
    return next
  })

  const save = async () => {
    if (!rtParams) return
    setSaving(true); setNote(null)
    try {
      await axios.post(`${API}/trading-params`, {
        dry_run:              rtParams.dry_run ?? true,
        max_position_capital: Number(vals.max_position_capital) || 1000000,
        max_daily_positions:  Number(vals.max_daily_positions)  || 3,
        commission_discount:  Number(vals.commission_discount)  || 0.28,
        cb_crash_pct:         Number(vals.cb_crash_pct)         || 1.5,
        cb_window_min:        Number(vals.cb_window_min)        || 5,
        cb_pause_minutes:     Number(vals.cb_pause_minutes)     || 30,
      })
      const cfgUpdate: Record<string, any> = {}
      for (const p of PARAM_DEFS) {
        if (p.source === 'cfg' && (enabled[p.id] ?? true) && vals[p.id] != null)
          cfgUpdate[p.cfgPath!] = vals[p.id]
      }
      if (Object.keys(cfgUpdate).length) await axios.post(`${API}/config/update`, cfgUpdate)
      setNote({ ok: true, msg: '✓ 已儲存。config.yaml 參數需重啟引擎後生效。' })
    } catch (e: any) {
      setNote({ ok: false, msg: `✕ 儲存失敗：${e?.response?.data?.detail ?? e.message}` })
    } finally { setSaving(false) }
  }

  if (!rtParams || !cfgData)
    return <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>

  const isDry = rtParams?.dry_run ?? true

  return (
    <div className="space-y-4">
      {/* DRY RUN 橫幅 */}
      <div className={`${card} px-5 py-3 flex items-center justify-between`}>
        <span className={`text-sm font-bold ${isDry ? 'text-blue-400' : 'text-red-400'}`}>
          {isDry ? '🔵 模擬模式（Dry Run）' : '🔴 實盤模式（LIVE）'}
        </span>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <div className="relative w-10 h-5">
            <input type="checkbox" className="sr-only" checked={isDry}
              onChange={e => setRtParams({ ...rtParams, dry_run: e.target.checked })} />
            <div className={`w-10 h-5 rounded-full transition-colors ${isDry ? 'bg-blue-500' : 'bg-red-500'}`} />
            <div className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${isDry ? 'translate-x-0.5' : 'translate-x-5'}`} />
          </div>
          <span className={`text-sm ${muted}`}>Dry Run</span>
        </label>
      </div>
      {!isDry && (
        <div className="bg-red-900/20 border border-red-500/30 rounded-lg px-4 py-2 text-sm text-red-400">
          ⚠ 關閉 Dry Run 後將進行真實交易，請確認所有設定正確
        </div>
      )}

      {/* 儲存按鈕（在 list 上方） */}
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={save} disabled={saving}
          className="px-6 py-2 bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm rounded-lg font-semibold disabled:opacity-50">
          {saving ? '儲存中...' : '儲存全部設定'}
        </button>
        <span className={`text-xs ${muted}`}>
          ⚡ <span className="text-blue-400/80">即時生效</span>　⚙ <span className="text-amber-400/80">yaml — 需重啟引擎</span>
        </span>
        {note && <span className={`text-xs font-medium ${note.ok ? 'text-green-400' : 'text-red-400'}`}>{note.msg}</span>}
      </div>

      {/* 參數清單表格 */}
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full min-w-[640px]">
          <thead className="bg-[#0d1f35] border-b border-[#253d5c]">
            <tr>
              <th className="px-3 py-2.5 text-center text-xs text-[#6b84a0] w-10">啟用</th>
              <th className="px-3 py-2.5 text-left   text-xs text-[#6b84a0] w-40">參數</th>
              <th className="px-3 py-2.5 text-left   text-xs text-[#6b84a0]">說明</th>
              <th className="px-3 py-2.5 text-right  text-xs text-[#6b84a0] w-28">數值</th>
              <th className="px-3 py-2.5 text-left   text-xs text-[#6b84a0] w-16">單位</th>
            </tr>
          </thead>
          <tbody>
            {_PARAM_GROUPS.map(group => (
              <>
                <tr key={`g-${group}`} className="bg-[#10243e]">
                  <td colSpan={5} className="px-3 py-1.5">
                    <span className="text-[11px] font-bold text-[#60a5fa] tracking-widest uppercase">{group}</span>
                  </td>
                </tr>
                {PARAM_DEFS.filter(p => p.group === group).map(p => {
                  const on = enabled[p.id] ?? true
                  return (
                    <tr key={p.id}
                      className={`border-b border-[#1a2d4a] transition-colors ${on ? 'hover:bg-[#162336]' : 'opacity-40'}`}>
                      <td className="px-3 py-2.5 text-center">
                        {p.canDisable ? (
                          <button onClick={() => toggle(p.id)}
                            className={`w-4 h-4 rounded border-2 inline-flex items-center justify-center transition-colors
                              ${on ? 'bg-blue-500 border-blue-500' : 'border-[#4a6080] bg-transparent'}`}>
                            {on && <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                              <path d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"/>
                            </svg>}
                          </button>
                        ) : (
                          <div className="w-4 h-4 rounded border-2 border-[#253d5c] inline-flex items-center justify-center" title="必要參數">
                            <div className="w-1.5 h-1.5 rounded-sm bg-[#4a6080]" />
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className={`text-xs font-semibold text-[#dde6f0] ${!on ? 'line-through' : ''}`}>{p.label}</div>
                        <div className={`text-[10px] mt-0.5 ${p.source === 'cfg' ? 'text-amber-400/70' : 'text-blue-400/70'}`}>
                          {p.source === 'cfg' ? '⚙ yaml' : '⚡ 即時'}
                        </div>
                      </td>
                      <td className={`px-3 py-2.5 text-xs ${muted} leading-relaxed`}>{p.desc}</td>
                      <td className="px-3 py-2.5 text-right">
                        <input
                          type={p.type === 'time' ? 'text' : 'number'}
                          value={vals[p.id] ?? ''}
                          disabled={!on}
                          step={p.step}
                          min={p.min}
                          max={p.max}
                          onChange={e => setVals(prev => ({
                            ...prev,
                            [p.id]: p.type === 'time' ? e.target.value : Number(e.target.value)
                          }))}
                          className={`w-24 text-right bg-[#0c1929] border border-[#253d5c] text-[#dde6f0]
                            px-2 py-1 text-xs ${mono} rounded focus:outline-none focus:border-[#60a5fa]
                            disabled:opacity-40 disabled:cursor-not-allowed`}
                        />
                      </td>
                      <td className={`px-3 py-2.5 text-xs ${muted}`}>{p.unit}</td>
                    </tr>
                  )
                })}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── 系統設定 ─────────────────────────────────────────────────────────────────
function ConfigTab() {
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [engineState, setEngineState] = useState<any>(null)
  const [sysStatus, setSysStatus] = useState<any>(null)
  const [cfg, setCfg] = useState<any>(null)
  const [restarting, setRestarting] = useState(false)
  const [connSettings, setConnSettings] = useState({
    apiUrl: '/fubon-api',
    dailyDb: '/fubon-data/daily.db',
    ticksDb: '/fubon-data/ticks.db',
    refreshInterval: 1,
  })
  const [applied, setApplied] = useState(false)

  useEffect(() => {
    axios.get(`${API}/health`).then(() => setApiOk(true)).catch(() => setApiOk(false))
    axios.get(`${API}/system-status`).then(r => setSysStatus(r.data)).catch(() => {})
    axios.get(`${API}/config`).then(r => setCfg(r.data)).catch(() => {})
    axios.get(`${API}/engine/status`).then(r => setEngineState(r.data)).catch(() => {})
  }, [])

  const restartFastapi = () => {
    if (!window.confirm('確定要重啟 API server？重啟期間（約 3 秒）Dashboard 暫時無法存取，WebSocket 會自動重連。')) return
    setRestarting(true)
    axios.post(`${API}/restart/fastapi`).catch(() => {})
    setTimeout(() => window.location.reload(), 4000)
  }

  const st = sysStatus
  const trading = cfg?.trading ?? {}
  const fubon = cfg?.fubon ?? {}
  const watchlist: string[] = trading.dry_run_watchlist ?? cfg?.watchlist ?? []
  const engStatus: string = engineState?.status ?? 'unknown'
  const engRunning = engStatus === 'running'

  const ServiceRow = ({ name, subtitle, running, pid, logPath, onRestart, restartDisabledReason }: {
    name: string; subtitle: string; running: boolean | null; pid?: number | null; logPath?: string
    onRestart?: () => void; restartDisabledReason?: string
  }) => (
    <div className="py-4 border-b border-[#253d5c] last:border-0">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-sm font-semibold text-[#dde6f0]">{name}</span>
          <div className="mt-0.5">
            <span className={`text-xs font-medium ${running ? 'text-green-400' : running === false ? 'text-red-400' : muted}`}>
              {running ? '● 運行中' : running === false ? '● 已停止' : '○ 偵測中'}
              {pid ? ` PID ${pid}` : ''}
            </span>
          </div>
          {restartDisabledReason && <div className={`text-[10px] ${muted} mt-0.5`}>{restartDisabledReason}</div>}
        </div>
        <div className="flex gap-2">
          {onRestart ? (
            <button onClick={onRestart} disabled={restarting}
              className="px-4 py-1.5 text-xs rounded border border-[#60a5fa] text-[#60a5fa] hover:bg-[#1e3a5f] disabled:opacity-50">
              {restarting ? '重啟中...' : '重啟'}
            </button>
          ) : (
            <button disabled className={`px-4 py-1.5 text-xs rounded border border-[#253d5c] ${muted} opacity-50 cursor-not-allowed`}>重啟</button>
          )}
          <button onClick={() => window.open(`${API}/logs/latest`, '_blank')}
            className={`px-4 py-1.5 text-xs rounded border border-[#253d5c] ${muted} hover:text-[#dde6f0] hover:border-[#60a5fa]`}>查看 log</button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="space-y-6 max-w-7xl">
      {/* 服務狀態 */}
      <div>
        <SectionLabel>服務狀態</SectionLabel>
        <div className={card}>
          <div className="px-5">
            <ServiceRow
              name="當沖 API (WSL :8090)"
              subtitle="WSL 直接執行（python run.py）"
              running={apiOk}
              logPath="/logs/latest"
              onRestart={restartFastapi}
            />
            <ServiceRow
              name="交易引擎（DailyScheduler）"
              subtitle="08:30 自動啟動，13:36 自動停止"
              running={engRunning ? true : engStatus === 'stopped' ? false : null}
              logPath="/logs/latest"
            />
          </div>
        </div>
      </div>

      {/* 連線設定 */}
      <div>
        <SectionLabel>連線設定</SectionLabel>
        <div className={`${card} p-5 space-y-5`}>
          <div>
            <label className={`text-xs ${muted} block mb-1`}>FastAPI URL</label>
            <input type="text" value={connSettings.apiUrl}
              onChange={e => setConnSettings({ ...connSettings, apiUrl: e.target.value })}
              className={`w-full bg-[#0c1929] border border-[#253d5c] text-[#dde6f0] rounded-lg px-3 py-2 text-sm ${mono} focus:outline-none focus:border-[#60a5fa]`}
            />
          </div>
          <div>
            <label className={`text-xs ${muted} block mb-1`}>daily.db 路徑</label>
            <input type="text" value={connSettings.dailyDb}
              onChange={e => setConnSettings({ ...connSettings, dailyDb: e.target.value })}
              className={`w-full bg-[#0c1929] border border-[#253d5c] text-[#dde6f0] rounded-lg px-3 py-2 text-sm ${mono} focus:outline-none focus:border-[#60a5fa]`}
            />
          </div>
          <div>
            <label className={`text-xs ${muted} block mb-1`}>ticks.db 路徑</label>
            <input type="text" value={connSettings.ticksDb}
              onChange={e => setConnSettings({ ...connSettings, ticksDb: e.target.value })}
              className={`w-full bg-[#0c1929] border border-[#253d5c] text-[#dde6f0] rounded-lg px-3 py-2 text-sm ${mono} focus:outline-none focus:border-[#60a5fa]`}
            />
          </div>
          <div className={`text-xs ${muted} pt-1`}>
            即時資料透過 WebSocket 推送，無需設定刷新間隔
          </div>
        </div>
        <button onClick={() => setApplied(true)}
          className="mt-3 px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg">
          套用
        </button>
        {applied && <span className={`ml-3 text-xs text-green-400`}>✓ 已套用</span>}
      </div>

      {/* 帳號 */}
      {fubon.id && (
        <div>
          <SectionLabel>帳號資訊</SectionLabel>
          <div className={`${card} p-4`}>
            <div className="flex justify-between py-1.5 border-b border-[#253d5c]">
              <span className={`text-xs ${muted}`}>帳號</span>
              <span className={`text-xs ${mono} text-[#60a5fa]`}>{fubon.id}</span>
            </div>
            <div className="flex justify-between py-1.5 border-b border-[#253d5c]">
              <span className={`text-xs ${muted}`}>憑證路徑</span>
              <span className={`text-xs ${mono} text-[#dde6f0] text-right`}>{fubon.cert_path}</span>
            </div>
            <div className="flex justify-between py-1.5">
              <span className={`text-xs ${muted}`}>密碼</span>
              <span className={`text-xs ${mono} ${muted}`}>●●●●●●●●</span>
            </div>
          </div>
        </div>
      )}

      {/* 監控清單 */}
      {watchlist.length > 0 && (
        <div>
          <SectionLabel>監控清單（{watchlist.length} 檔）</SectionLabel>
          <div className={`${card} p-3`}>
            <div className="flex flex-wrap gap-1.5">
              {watchlist.map((s: string) => (
                <span key={s} className={`bg-[#0c1929] border border-[#253d5c] rounded px-2 py-0.5 text-xs ${mono} text-[#dde6f0]`}>{s}</span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── LINE 模擬通知測試 ─────────────────────────────────────────────────────────
function SimulateBuySell() {
  const [symbol, setSymbol] = useState('2382')
  const [price, setPrice] = useState('250')
  const [lots, setLots] = useState('1')
  const [exitPrice, setExitPrice] = useState('')
  const [simPos, setSimPos] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const doBuy = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await axios.post(`${API}/debug/simulate-buy`, null, {
        params: { symbol, price: Number(price) || 250, lots: Number(lots) || 1 }
      })
      setSimPos(r.data)
      setExitPrice(String((r.data.stop_loss ?? 0).toFixed(1)))
      setMsg({ ok: true, text: `✓ 模擬買入 ${symbol}，LINE 已送出` })
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally { setBusy(false) }
  }

  const doSell = async () => {
    setBusy(true); setMsg(null)
    try {
      const r = await axios.post(`${API}/debug/simulate-sell`, null, {
        params: { symbol, price: Number(exitPrice) || 0, reason: 'atr_stop' }
      })
      setMsg({ ok: true, text: `✓ 模擬出場 ${symbol}，損益 ${r.data.pnl >= 0 ? '+' : ''}${r.data.pnl.toLocaleString()}，LINE 已送出` })
      setSimPos(null)
    } catch (e: any) {
      setMsg({ ok: false, text: `✕ ${e?.response?.data?.detail ?? e.message}` })
    } finally { setBusy(false) }
  }

  return (
    <div className={card}>
      <div className={`px-4 py-2 border-b border-[#253d5c] text-sm font-semibold text-[#dde6f0]`}>
        LINE 通知測試（模擬買賣）
      </div>
      <div className="px-4 py-3 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className={`text-[10px] uppercase tracking-wide ${muted}`}>股票代號</span>
            <input value={symbol} onChange={e => setSymbol(e.target.value)}
              className="w-20 px-2 py-1 text-sm bg-[#0d1b2b] border border-[#253d5c] rounded text-[#dde6f0]" />
          </label>
          <label className="flex flex-col gap-1">
            <span className={`text-[10px] uppercase tracking-wide ${muted}`}>買入價</span>
            <input value={price} onChange={e => setPrice(e.target.value)} type="number"
              className="w-24 px-2 py-1 text-sm bg-[#0d1b2b] border border-[#253d5c] rounded text-[#dde6f0]" />
          </label>
          <label className="flex flex-col gap-1">
            <span className={`text-[10px] uppercase tracking-wide ${muted}`}>張數</span>
            <input value={lots} onChange={e => setLots(e.target.value)} type="number" min={1}
              className="w-16 px-2 py-1 text-sm bg-[#0d1b2b] border border-[#253d5c] rounded text-[#dde6f0]" />
          </label>
          <button onClick={doBuy} disabled={busy || !!simPos}
            className="px-4 py-1.5 text-xs rounded border border-green-400 text-green-400 hover:bg-green-400/10 disabled:opacity-40">
            模擬買入
          </button>
        </div>
        {simPos && (
          <div className="flex flex-wrap items-end gap-3">
            <div className={`text-xs ${muted}`}>
              持倉：{simPos.symbol} @ {simPos.entry_price}  停損={simPos.stop_loss?.toFixed(2)}  張={simPos.lots}
            </div>
            <label className="flex flex-col gap-1">
              <span className={`text-[10px] uppercase tracking-wide ${muted}`}>出場價（預設停損）</span>
              <input value={exitPrice} onChange={e => setExitPrice(e.target.value)} type="number"
                className="w-24 px-2 py-1 text-sm bg-[#0d1b2b] border border-[#253d5c] rounded text-[#dde6f0]" />
            </label>
            <button onClick={doSell} disabled={busy}
              className="px-4 py-1.5 text-xs rounded border border-red-400 text-red-400 hover:bg-red-400/10 disabled:opacity-40">
              模擬出場
            </button>
          </div>
        )}
        {msg && (
          <div className={`text-xs ${msg.ok ? 'text-green-400' : 'text-red-400'}`}>{msg.text}</div>
        )}
      </div>
    </div>
  )
}

// ── 系統健診 ─────────────────────────────────────────────────────────────────
function HealthTab() {
  const [result, setResult] = useState<any | null>(null)
  const [running, setRunning] = useState(false)
  const [logs, setLogs] = useState<{ lines: string[]; file: string | null; date: string | null }>({ lines: [], file: null, date: null })
  const [engineState, setEngineState] = useState<any>(null)
  const stream = useEngineStream()

  // WebSocket 推送：取代 /engine/status 5秒輪詢
  useEffect(() => {
    if (stream && stream.type === 'state') setEngineState(stream)
  }, [stream])

  const refreshLogs = () =>
    axios.get(`${API}/logs/latest?lines=100`).then(r => setLogs({ lines: r.data.lines, file: r.data.file, date: r.data.date })).catch(() => {})

  useEffect(() => {
    axios.get(`${API}/health-check/results`).then(r => { if (r.data?.results?.length) setResult(r.data) }).catch(() => {})
    refreshLogs()
    axios.get(`${API}/engine/status`).then(r => setEngineState(r.data)).catch(() => {})
  }, [])

  const engStatus: string = engineState?.status ?? 'unknown'
  const engRunning = engStatus === 'running'
  const engTransient = engStatus === 'starting' || engStatus === 'stopping'
  const engColor = engRunning ? 'text-green-400' : engTransient ? 'text-yellow-400' : engStatus === 'error' ? 'text-red-400' : muted
  const engLabel = engRunning ? '● 運行中' : engTransient ? `○ ${engStatus === 'starting' ? '啟動中...' : '停止中...'}` : engStatus === 'error' ? '● 異常' : engStatus === 'stopped' ? '● 已停止' : '○ 偵測中'

  const runCheck = (mode: 'quick' | 'full') => {
    setRunning(true)
    axios.post(`${API}/health-check/run?mode=${mode}`)
      .then(r => setResult(r.data))
      .catch(() => {})
      .finally(() => setRunning(false))
  }

  const items: any[] = result?.results ?? []
  const summ = result?.summary ?? {}

  const icon = (r: any) =>
    r.ok && !r.warn ? <span className="text-green-400">✔</span>
    : r.warn        ? <span className="text-yellow-400">⚠</span>
    : <span className="text-red-400">✘</span>

  const valCls = (r: any) =>
    r.ok && !r.warn ? 'text-[#dde6f0]' : r.warn ? 'text-yellow-400' : 'text-red-400'

  const tsDisplay = result?.ts
    ? new Date(result.ts).toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false })
    : null

  return (
    <div className="space-y-4">
      {/* 引擎狀態（唯讀，DailyScheduler 自動管理） */}
      <div className={`${card} px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs`}>
        <span className={`font-semibold text-sm ${engColor}`}>引擎 {engLabel}</span>
        {engRunning && engineState?.tick_count != null && (
          <span className={muted}>{engineState.tick_count.toLocaleString()} ticks</span>
        )}
        {engineState?.pnl && engRunning && (
          <span className={`${mono} ${(engineState.pnl.actual_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            實際 {(engineState.pnl.actual_pnl ?? 0) >= 0 ? '+' : ''}{(engineState.pnl.actual_pnl ?? 0).toLocaleString()}
            　理論 {(engineState.pnl.paper_pnl ?? 0) >= 0 ? '+' : ''}{(engineState.pnl.paper_pnl ?? 0).toLocaleString()}
          </span>
        )}
        {engineState?.started_at && (
          <span className={muted}>啟動：{new Date(engineState.started_at).toLocaleTimeString('zh-TW', { hour12: false })}</span>
        )}
        {engineState?.dry_run != null && <span className="text-blue-400">DRY RUN</span>}
        {engineState?.symbols?.length > 0 && <span className={muted}>監控：{engineState.symbols.join(', ')}</span>}
        {engineState?.error && <span className="text-red-400 w-full">{engineState.error}</span>}
        <span className={`ml-auto text-[10px] ${muted}`}>DailyScheduler 08:30 自動啟動 / 13:36 自動停止</span>
      </div>

      {/* 快速/完整健診 buttons */}
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => runCheck('quick')} disabled={running}
          className="flex items-center gap-2 px-4 py-2 bg-[#1e3a5f] hover:bg-[#253d5c] text-[#dde6f0] text-sm font-semibold rounded-lg border border-[#253d5c] disabled:opacity-50">
          ⚡ 快速健診
        </button>
        <button onClick={() => runCheck('full')} disabled={running}
          className="flex items-center gap-2 px-4 py-2 bg-[#142035] hover:bg-[#1a2d4a] text-[#dde6f0] text-sm font-semibold rounded-lg border border-[#253d5c] disabled:opacity-50">
          🔍 完整健診 (含 SDK)
        </button>
        {running && <span className={`text-xs ${muted}`}>執行中...</span>}
      </div>

      {/* LINE 模擬通知測試 */}
      <SimulateBuySell />

      {/* Summary bar */}
      {result && (
        <div className="flex items-center gap-3 text-xs flex-wrap">
          {tsDisplay && <span className={muted}>{tsDisplay}</span>}
          <span className={`${muted} border-l border-[#253d5c] pl-3`}>
            {result.no_sdk ? '快速模式（略過 SDK）' : '完整模式（含 SDK）'}
          </span>
          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-green-400/15 text-green-400 font-semibold">✔ {summ.hard_ok ?? 0}</span>
          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-red-400/15 text-red-400 font-semibold">✘ {summ.hard_fail ?? 0}</span>
          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-yellow-400/15 text-yellow-400 font-semibold">⚠ {summ.soft_warn ?? 0}</span>
        </div>
      )}

      {/* Check table */}
      <div className={card}>
        {!result && !running ? (
          <div className={`text-center py-10 text-sm ${muted}`}>點擊上方按鈕執行健診</div>
        ) : running && !result ? (
          <div className={`text-center py-10 text-sm ${muted}`}>執行中...</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`text-[11px] ${muted} border-b border-[#253d5c] whitespace-nowrap`}>
                  <th className="px-3 py-2 w-6 text-center">燈</th>
                  <th className="px-3 py-2 text-left">項目</th>
                  <th className="px-3 py-2 text-left">資料來源 / 邏輯</th>
                  <th className="px-3 py-2 text-left">狀態 / 值</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r: any) => (
                  <tr key={r.item_id} className={`border-b border-[#253d5c] ${!r.ok && !r.warn ? 'bg-red-900/10' : ''}`}>
                    <td className="px-3 py-2 text-center">{icon(r)}</td>
                    <td className="px-3 py-2 text-xs font-semibold text-[#dde6f0] whitespace-nowrap">
                      {String(r.item_id).padStart(2,'0')} {r.name}
                    </td>
                    <td className={`px-3 py-2 text-xs ${muted} max-w-xs`}>
                      <div className="whitespace-normal leading-4">{r.data_source}</div>
                    </td>
                    <td className={`px-3 py-2 ${mono} text-xs ${valCls(r)} whitespace-normal`}>{r.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
            <div className={`text-xs ${muted}`}>無 log — 引擎尚未啟動或尚無記錄</div>
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
      <div className="max-w-7xl mx-auto">
        <div className="mb-5">
          <h1 className="text-2xl font-black text-[#dde6f0]">台股當沖</h1>
          <p className={`text-sm mt-0.5 ${muted}`}>富邦證券自動交易系統</p>
        </div>

        {/* Sub-tab bar */}
        <div className="flex gap-1 bg-[#142035] rounded-lg p-1 border border-[#253d5c] overflow-x-auto mb-6">
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
