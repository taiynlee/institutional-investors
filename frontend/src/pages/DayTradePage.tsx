import { type ReactNode, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { ManualTradeContent } from './ManualTradePage'

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

type SubTab = 'live' | 'manual' | 'trades' | 'pre-session' | 'params' | 'config' | 'health' | 'line-log'

const SUB_TABS: { id: SubTab; label: string }[] = [
  { id: 'live',        label: '今日交易' },
  { id: 'manual',     label: '手動買賣' },
  { id: 'trades',      label: '交易紀錄' },
  { id: 'pre-session', label: '當沖篩選' },
  { id: 'params',      label: '交易設定' },
  { id: 'config',      label: '後台設定' },
  { id: 'health',      label: '當沖健診' },
  { id: 'line-log',    label: '訊息 Log' },
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

// ── 訊號 Log ─────────────────────────────────────────────────────────────────
const REASON_LABEL: Record<string, string> = {
  time_not_ok:              '時間窗口外',
  already_in_position:      '同標的持倉中',
  max_daily_trades_reached: '已達當日上限',
  ok:                       '全通過',
}
function reasonLabel(r: string | undefined | null): string {
  if (!r) return ''
  if (REASON_LABEL[r]) return REASON_LABEL[r]
  if (r.startsWith('change_pct_exceeded_'))  return `漲跌幅超限(${r.split('exceeded_')[1]})`
  if (r.startsWith('tick_rise_low_'))        return `tick+買盤均不足(${r.replace('tick_rise_low_', '')})`
  if (r.startsWith('bid_pct_low_'))          return `買盤不足(${r.split('low_')[1]}%)`
  if (r.startsWith('vol_ratio_low_'))        return `量比不足(${r.replace('vol_ratio_low_', '')})`
  if (r.startsWith('amplitude_low_'))        return `振幅不足(${r.replace('amplitude_low_', '')})`
  if (r === 'futures_not_leading')           return '期貨未領漲'
  return r
}

function SignalLogRow({ e, windowSecs = 60 }: { e: any; windowSecs?: number }) {
  if (e.type === 'buy') {
    return (
      <div className={`flex gap-1.5 items-baseline text-green-400`}>
        <span className="text-[#6b84a0] shrink-0">[{e.ts}]</span>
        <span className="shrink-0">🟢 BUY</span>
        <span className="font-bold shrink-0">{e.name} {e.symbol}</span>
        <span>{e.lots}張 @{e.price?.toFixed(1)}</span>
        <span className="text-orange-400">停損{e.stop_loss?.toFixed(1)}</span>
        <span className="text-green-300">停利{e.take_profit?.toFixed(1)}</span>
        {e.dry_run && <span className="text-blue-400 text-[10px]">[DRY]</span>}
      </div>
    )
  }
  if (e.type === 'sell') {
    const pnlCls = (e.pnl ?? 0) >= 0 ? 'text-red-400' : 'text-green-400'
    return (
      <div className={`flex gap-1.5 items-baseline text-red-400`}>
        <span className="text-[#6b84a0] shrink-0">[{e.ts}]</span>
        <span className="shrink-0">🔴 SELL</span>
        <span className="font-bold shrink-0">{e.name} {e.symbol}</span>
        <span>{e.lots}張</span>
        <span>{e.entry_price?.toFixed(1)}→{e.exit_price?.toFixed(1)}</span>
        <span className={pnlCls}>損益{(e.pnl ?? 0) >= 0 ? '+' : ''}{(e.pnl ?? 0).toLocaleString()}</span>
        <span className="text-[#6b84a0] text-[10px]">{e.reason}</span>
      </div>
    )
  }
  // eval
  const passed = e.passed === true
  return (
    <div className={`flex flex-wrap gap-1.5 items-baseline ${passed ? 'text-green-300' : 'text-yellow-400'}`}>
      <span className="text-[#6b84a0] shrink-0">[{e.ts}]</span>
      <span className="shrink-0">{passed ? '✅' : '⚠'}</span>
      <span className="font-bold shrink-0">{e.name} {e.symbol}</span>
      <span className={`${mono} text-[10px]`}>{windowSecs}s▲{e.tick_rise}t</span>
      <span className={`${mono} text-[10px]`}>買1m={e.bid_1m_pct}%</span>
      <span className={`${mono} text-[10px]`}>買盤={e.bid_pct}%</span>
      <span className={`${mono} text-[10px]`}>量比={e.vol_ratio}%(≥{e.vol_ratio_thr}%)</span>
      <span className={`${mono} text-[10px]`}>振幅={e.amplitude_pct}%</span>
      <span className={`${mono} text-[10px]`}>漲{e.change_pct}%</span>
      {!passed && <span className="text-red-400 text-[10px]">✗{reasonLabel(e.reason)}</span>}
    </div>
  )
}

function SignalLog({ entries, windowSecs, threshold }: { entries: any[]; windowSecs: number; threshold: number }) {
  return (
    <div className={card}>
      <div className="px-4 py-2 border-b border-[#253d5c] flex items-center gap-2">
        <span className="text-xs text-[#6b84a0]">訊號 Log</span>
        <span className={`text-[10px] ${muted}`}>{windowSecs}s tick ≥{threshold} 達標才記錄・最新在上・開盤前清除</span>
        {entries.length > 0 && <span className="ml-auto text-[10px] text-[#6b84a0]">{entries.length} 筆</span>}
      </div>
      {entries.length === 0
        ? <div className={`px-4 py-3 text-[11px] ${muted}`}>等待訊號觸發...</div>
        : (
          <div className={`overflow-y-auto max-h-[260px] px-3 py-2 space-y-[3px] font-mono text-[11px]`}>
            {entries.map((e, i) => <SignalLogRow key={i} e={e} windowSecs={windowSecs} />)}
          </div>
        )
      }
    </div>
  )
}

// ── 今日交易 ─────────────────────────────────────────────────────────────────
const _minsNow = () => { const n = new Date(); return n.getHours() * 60 + n.getMinutes() }
const _CLOSE_MINS = 13 * 60 + 31  // 13:31 判定收盤

function LiveTab() {
  const [list, setList] = useState<any | null>(null)
  const [status, setStatus] = useState<{ total_pnl: number; trade_count: number } | null>(null)
  const [positions, setPositions] = useState<any[]>([])
  const [ticks, setTicks] = useState<Record<string, any>>({})
  const [futures, setFutures] = useState<Record<string, any>>({})
  const [engineRunning, setEngineRunning] = useState<boolean | null>(null)
  const evsRef = useRef<EventSource | null>(null)
  const [loading, setLoading] = useState(true)
  const [listRefreshing, setListRefreshing] = useState(false)
  const [closedAt, setClosedAt] = useState<string | null>(
    () => _minsNow() >= _CLOSE_MINS ? '13:30' : null
  )
  const stream = useEngineStream()
  const [cancellingCond, setCancellingCond] = useState<string | null>(null)

  // WebSocket 推送：取代 /status + /positions + /engine/status 輪詢
  useEffect(() => {
    if (!stream) return
    setEngineRunning(stream.status === 'running')
    if (stream.pnl) setStatus({ total_pnl: stream.pnl.actual_pnl ?? 0, trade_count: stream.pnl.actual_trades ?? 0 })
    if (Array.isArray(stream.positions)) setPositions(stream.positions)
  }, [stream])

  // 收盤計時器
  useEffect(() => {
    if (closedAt) return
    const minsLeft = _CLOSE_MINS - _minsNow()
    if (minsLeft <= 0) { setClosedAt('13:30'); return }
    const t = setTimeout(() => setClosedAt('13:30'), minsLeft * 60 * 1000)
    return () => clearTimeout(t)
  }, [closedAt])

  const doRefreshList = (quiet = false) => {
    if (!quiet) setListRefreshing(true)
    axios.get(`${API}/daytrade-list`)
      .then(r => setList(r.data))
      .catch(() => {})
      .finally(() => { if (!quiet) setListRefreshing(false) })
  }

  useEffect(() => {
    setLoading(true)
    axios.get(`${API}/daytrade-list`)
      .then(r => setList(r.data))
      .catch(() => setList(null))
      .finally(() => setLoading(false))
  }, [])

  // 盤中每 5 分鐘自動刷新名單（收盤後停止）
  useEffect(() => {
    if (closedAt) return
    const tid = setInterval(() => {
      const m = _minsNow()
      if (m >= 8 * 60 + 30 && m < _CLOSE_MINS) doRefreshList(true)
    }, 5 * 60 * 1000)
    return () => clearInterval(tid)
  }, [closedAt])

  useEffect(() => {
    if (!list?.stocks?.length) return
    const syms = list.stocks.map((s: any) => s.stock_id).join(',')
    if (evsRef.current) evsRef.current.close()
    const evs = new EventSource(`${API}/stream?syms=${syms}`)
    // merge 策略：SSE 送空 {} 或部分資料時不覆蓋舊值，保留收盤快照
    evs.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        if (Object.keys(d).length > 0) setTicks(prev => ({ ...prev, ...d }))
      } catch {}
    }
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

  const cancelConditions = async (symbol: string) => {
    setCancellingCond(symbol)
    try {
      await axios.post(`${API}/engine/cancel-conditions/${symbol}`)
      alert(`✓ ${symbol} 觸價單已取消，可安全從手機賣出`)
    } catch (e: any) {
      alert(`✕ ${e?.response?.data?.detail ?? e.message}`)
    } finally {
      setCancellingCond(null)
    }
  }

  const pnlColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-[#6b84a0]'

  const stocks: any[] = list?.stocks ?? []
  const idxData = ticks['__index__'] ?? {}
  const idxPrice: number | null = idxData.price ?? null
  const idxChgDayPct: number = idxData.chg_day_pct ?? 0

  return (
    <div className="space-y-4">
      {/* 6 top metrics row */}
      <div className="grid grid-cols-6 gap-2">
        {/* 模式（dry_run 熱重載）*/}
        <div className={`${card} px-3 py-3 flex flex-col justify-center`}>
          <span className="text-[10px] text-[#6b84a0] mb-0.5">模式</span>
          {stream?.dry_run !== false
            ? <span className="text-xs font-bold text-blue-400">● DRY RUN 模擬</span>
            : <span className="text-xs font-bold text-red-400">● 實盤 LIVE</span>
          }
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
        <div
          className={`${card} px-3 py-3 flex flex-col justify-center cursor-help`}
          title={(() => {
            const est = stream?.entry_start_time ?? '09:15'
            const [_h, _m] = est.split(':').map(Number)
            const _mins = _h * 60 + _m - 9 * 60
            const _coef = (stream as any)?.vol_ratio_coefficient ?? 1.3
            const _volPct = Math.round(_mins * _coef * 10) / 10
            return `進場八條件：\n① 時間窗口（進場開始 ~ 進場截止）\n② 同標的當下未持倉（可關閉）\n③ 今日進場次數 < max_daily_positions\n④ 個股漲跌幅在 ±max_change_pct 內\n⑤ ⭐必要（二擇一）：${stream?.tick_window_seconds ?? 60}秒內上漲 ≥ ${stream?.tick_rise_threshold ?? 4} tick，或觀察窗買盤佔比 ≥ ${stream?.bid_1m_pct_threshold ?? 70}%\n⑥ 若有個股期貨：期貨價 > 現價（正價差，可關閉）\n⑦ 今日累積量/5日均量 ≥ 開盤後觀察${_mins}分鐘×${_coef} = ${_volPct}%（係數可調）\n⑧ 振幅（今日動能）≥ ${stream?.amplitude_min_pct ?? 3}%（可調）`
          })()}
        >
          <span className="text-[10px] text-[#6b84a0] mb-0.5">今日已交易</span>
          <span className="text-base font-bold text-[#60a5fa]">
            {stream?.pnl?.daily_entries ?? 0}
            <span className="text-[#6b84a0] text-xs font-normal"> / {stream?.pnl?.max_daily ?? 5} 檔</span>
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
            {idxChgDayPct !== 0 && <span className={`text-[10px] ${mono} ${idxChgDayPct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
              {idxChgDayPct >= 0 ? '▲' : '▼'}{Math.abs(idxChgDayPct).toFixed(2)}%
            </span>}
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
                  <th className="px-4 py-2 text-right">停損</th>
                  <th className="px-4 py-2 text-right">停利</th>
                  <th className="px-4 py-2 text-right">未實現</th>
                  <th className="px-4 py-2 text-center w-20"></th>
                </tr>
              </thead>
              <tbody>
                {positions.map(p => {
                  const tk = ticks[p.symbol]
                  const cur = tk?.price ?? null
                  const unreal = cur != null ? (cur - p.entry_price) * p.lots * 1000 : null
                  const uc = unreal != null ? (unreal >= 0 ? 'text-red-400' : 'text-green-400') : muted
                  const nearStop = cur != null && p.stop_loss != null && cur <= p.stop_loss * 1.02
                  const nearTp = cur != null && p.take_profit != null && cur >= p.take_profit * 0.99
                  return (
                    <tr key={p.symbol} className="border-b border-[#253d5c] hover:bg-[#1a2d4a]">
                      <td className="px-4 py-2 text-[#60a5fa] font-bold">{p.symbol}</td>
                      <td className="px-4 py-2 text-right text-[#dde6f0]">{p.lots}</td>
                      <td className={`px-4 py-2 text-right ${mono} text-[#dde6f0]`}>{p.entry_price?.toFixed(1)}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${cur != null ? (cur >= p.entry_price ? 'text-red-400' : 'text-green-400') : muted}`}>{cur != null ? cur.toFixed(1) : '—'}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${nearStop ? 'text-red-400 font-bold' : 'text-orange-400'}`}>{p.stop_loss?.toFixed(1) ?? '—'}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${nearTp ? 'text-red-400 font-bold' : 'text-green-400'}`}>{p.take_profit?.toFixed(1) ?? '—'}</td>
                      <td className={`px-4 py-2 text-right ${mono} ${uc}`}>{unreal != null ? `${unreal >= 0 ? '+' : ''}${Math.round(unreal).toLocaleString()}` : '—'}</td>
                      <td className="px-4 py-2 text-center">
                        <button
                          onClick={() => cancelConditions(p.symbol)}
                          disabled={cancellingCond === p.symbol}
                          title="取消停損/停利觸價單（若要從手機 App 手動賣出，請先按此）"
                          className="text-[10px] px-1.5 py-0.5 rounded border border-orange-600/40 text-orange-400 hover:bg-orange-900/30 disabled:opacity-40 whitespace-nowrap"
                        >
                          {cancellingCond === p.symbol ? '取消中…' : '取消觸價單'}
                        </button>
                      </td>
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
        <div className="px-4 py-2 border-b border-[#253d5c] flex items-center gap-2 flex-wrap">
          <span
            className="text-sm font-semibold text-[#dde6f0] cursor-help border-b border-dotted border-[#4a6fa8]"
            title={`最新觀察名單 — 產生邏輯（每日 21:05 自動執行）\n\n四個來源取聯集：\n① 股票池 × 當沖篩選條件\n   必要條件（4條全過）：TWSE當沖標的 + 近5日均量≥2000張 + 收盤>MA20 + 外資淨+投信淨≥0\n   籌碼加分（≥2條）：外資買超 + 投信買超 + 融資日減\n② ∪ 策略A + 策略B 當日篩選結果\n③ ∪ 策略C 滿分100分\n   （月營收YoY≥10% + 連續加速 + 近2季EPS>0 + 各項評分滿分）\n④ ∪ A追蹤清單（status: tracking / triggered / entered）\n\n過濾：\n⑤ 扣除退場止損名單\n⑥ 昨收 200~990 元（可在當沖設定調整）`}
          >最新觀察名單</span>
          {list && <Badge text={`${list.count} 檔`} color="blue" />}
          {list?.date && <span className={`text-xs ${muted}`}>{list.date}</span>}
          {closedAt
            ? <span className="text-xs text-yellow-400 font-semibold ml-1">■ 已收盤 · 收盤快照</span>
            : (
              <button
                onClick={() => doRefreshList(false)}
                disabled={listRefreshing}
                className="ml-auto text-[10px] px-2 py-0.5 rounded border border-[#253d5c] text-[#6b84a0] hover:text-[#dde6f0] hover:border-[#4a6fa8] disabled:opacity-40 transition-colors"
              >
                {listRefreshing ? '更新中…' : '↻ 刷新名單'}
              </button>
            )
          }
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
                  <th className="px-3 py-2 text-left"  style={{minWidth:104}}>已成交買賣盤</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>期貨</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:50}}>差價</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>Open</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>High</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>Low</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:56}}>振幅%</th>
                  <th className="px-3 py-2 text-right" style={{minWidth:72}}>今日累積量/5日均量</th>
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
                      {/* 振幅% = (High - Low) / 昨收 × 100 */}
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs`}>
                        {high_v != null && low_v != null && ref ? (
                          <span className="text-yellow-300">
                            {((high_v - low_v) / ref * 100).toFixed(1)}%
                          </span>
                        ) : <span className={muted}>—</span>}
                      </td>
                      {/* 今日累積量 / 5日均量 % */}
                      <td className="px-3 py-2.5">
                        {vol != null && vol > 0 && s.avg_vol5 > 0 ? (() => {
                          const paceRaw = vol / s.avg_vol5 * 100
                          // 若 > 500% 代表 SDK 回傳分批競價累計量，顯示為異常
                          if (paceRaw > 500) return <span title="SDK累計量異常，股票可能為分批競價處置股" className={`text-[10px] ${mono} text-orange-400`}>⚠ 異常</span>
                          const barW    = Math.min(paceRaw, 100)
                          const barCl   = paceRaw >= 100 ? 'bg-green-400' : paceRaw >= 50 ? 'bg-yellow-400' : 'bg-[#6b84a0]'
                          const txtCl   = paceRaw >= 100 ? 'text-green-400' : paceRaw >= 50 ? 'text-yellow-400' : muted
                          const label   = paceRaw < 1 ? '<1%' : `${Math.round(paceRaw)}%`
                          return (
                            <div className="flex items-center gap-1.5" style={{width:72}}>
                              <div className="h-[4px] rounded bg-[#253d5c] flex-1">
                                <div className={`h-full rounded ${barCl}`} style={{width:`${barW}%`}} />
                              </div>
                              <span className={`text-[10px] ${mono} ${txtCl} shrink-0`}>{label}</span>
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

      {/* 訊號 Log */}
      <SignalLog
        entries={stream?.signal_log ?? []}
        windowSecs={stream?.tick_window_seconds ?? 60}
        threshold={stream?.tick_rise_threshold ?? 4}
      />
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

// ── 當沖篩選 ─────────────────────────────────────────────────────────────────
function PreSessionTab() {
  const [dates, setDates]       = useState<{ date: string; count: number }[]>([])
  const [selDate, setSelDate]   = useState('')
  const [list, setList]         = useState<any | null>(null)
  const [listLoading, setListLoading] = useState(false)
  const [priceMin, setPriceMin] = useState<number>(200)
  const [priceMax, setPriceMax] = useState<number>(990)

  useEffect(() => {
    axios.get(`${API}/trading-params`).then(r => {
      if (r.data.daytrade_price_min != null) setPriceMin(r.data.daytrade_price_min)
      if (r.data.daytrade_price_max != null) setPriceMax(r.data.daytrade_price_max)
    }).catch(() => {})
  }, [])

  useEffect(() => {
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

  const stocks: any[] = list?.stocks ?? []

  const ck  = (v: boolean) => v
    ? <span className="text-green-400 font-bold text-xs">✔</span>
    : <span className="text-red-400 font-bold text-xs">✘</span>
  const chip = (v: boolean) => v
    ? <span className="text-green-400 text-xs">●</span>
    : <span className={`${muted} text-xs`}>○</span>

  return (
    <div className="space-y-4">
      {/* 日期選擇 */}
      {dates.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-xs ${muted} mr-1`}>選股日期</span>
          {dates.map(d => (
            <button key={d.date} onClick={() => setSelDate(d.date)}
              className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                selDate === d.date
                  ? 'bg-[#1e3a5f] text-[#dde6f0] ring-1 ring-[#60a5fa]'
                  : 'bg-[#142035] border border-[#253d5c] text-[#6b84a0] hover:text-[#dde6f0]'
              }`}>
              {d.date} <span className={muted}>({d.count})</span>
            </button>
          ))}
        </div>
      )}

      {/* 篩選條件說明 */}
      <div className={`${card} px-4 py-3`}>
        <div className={`text-[10px] uppercase tracking-widest ${muted} mb-3`}>最新觀察名單產生邏輯（每日 21:05）</div>
        <div className="space-y-3 text-xs text-[#dde6f0]">
          <div>
            <div className="font-semibold text-[#60a5fa] mb-1">① 股票池 × 篩選條件</div>
            <div className="pl-3 space-y-0.5">
              <div className="text-[#6b84a0] text-[11px]">籌碼加分 ≥ 2 條入選</div>
              <div>⬡ 外資昨日買超（foreign_net &gt; 0）</div>
              <div>⬡ 投信連續買超（trust_net &gt; 0）</div>
              <div>⬡ 融資餘額日減少（margin_change &lt; 0）</div>
            </div>
          </div>
          <div>
            <div className="font-semibold text-[#60a5fa] mb-0.5">② ∪ 策略A + 策略B 當日篩選結果</div>
          </div>
          <div>
            <div className="font-semibold text-[#60a5fa] mb-0.5">③ ∪ 策略C 當日名單（全部納入）</div>
          </div>
          <div className="pt-1 border-t border-[#253d5c]">
            <div className="font-semibold text-[#f59e0b] mb-0.5">過濾</div>
            <div>昨收 {priceMin}~{priceMax} 元　·　處置股全排除</div>
          </div>
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
                        {s.foreign_net > 0 ? '+' : ''}{s.foreign_net != null ? Math.round(s.foreign_net).toLocaleString() : '—'}
                      </td>
                      <td className={`px-3 py-2.5 text-right ${mono} text-xs ${truOk ? 'text-green-400' : 'text-red-400'}`}>
                        {s.trust_net > 0 ? '+' : ''}{s.trust_net != null ? Math.round(s.trust_net).toLocaleString() : '—'}
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

    </div>
  )
}

// ── 交易設定 ─────────────────────────────────────────────────────────────────
interface PD { id: string; group: string; label: string; desc: string; unit: string; rtKey: string; type: 'number'|'time'|'boolean'; step?: number; min?: number; max?: number }
const PARAM_DEFS: PD[] = [
  // 倉位控制
  { id:'max_position_capital', group:'倉位控制', label:'每次進場資金上限', desc:'每次進場最多動用的資金（超過就截斷）；張數 = floor(min(上限, 剩餘總資金) / (價格 × 1000))', unit:'TWD', rtKey:'max_position_capital', type:'number', step:100000, min:100000 },
  { id:'max_daily_positions',  group:'倉位控制', label:'每日進場次數上限', desc:'一天最多進場幾次（同標的可重複計入）；達上限後當日不再開新倉', unit:'次', rtKey:'max_daily_positions', type:'number', step:1, min:1 },
  // 進場條件（由常調 → 少調排序）
  { id:'tick_rise_threshold',      group:'進場條件', label:'tick 上漲門檻',          desc:'觀察窗口內股價上漲需 ≥ 此 tick 數才觸發進場；tick 依各價位不同計算', unit:'tick', rtKey:'tick_rise_threshold', type:'number', step:1, min:1 },
  { id:'bid_1m_pct_threshold',     group:'進場條件', label:'觀察窗口買盤佔比門檻',   desc:'條件⑤的第二觸發路徑：觀察窗口（tick_window_seconds）內買盤佔總成交量 >= 此%，即使上漲 tick 數不足，也允許進場。預設 70%，與「上漲 N tick」為二擇一', unit:'%', rtKey:'bid_1m_pct_threshold', type:'number', step:5, min:50, max:100 },
  { id:'amplitude_min_pct',        group:'進場條件', label:'振幅門檻',               desc:'振幅 = (當日最高價 − 最低價) / 昨收 × 100%，反映這支股票今天的動能。振幅太低代表盤整沒方向，不適合當沖，建議設 3~5%', unit:'%', rtKey:'amplitude_min_pct', type:'number', step:0.5, min:0, max:20 },
  { id:'vol_ratio_coefficient',    group:'進場條件', label:'量比係數',               desc:'條件⑧量比門檻 = (進場開始時間 − 09:00 分鐘數) × 此係數。例：09:15進場、係數1.3 → 門檻=19.5%。係數越高代表要求開盤後的交易量相對5日均量越活躍才進場。預設1.3，可調整範圍0.5~5', unit:'', rtKey:'vol_ratio_coefficient', type:'number', step:0.1, min:0.1, max:5 },
  { id:'tick_window_seconds',      group:'進場條件', label:'tick 觀察窗口',          desc:'計算 tick_rise 用的滾動時間窗口（秒）；預設60秒 = 看過去1分鐘漲了幾tick', unit:'秒', rtKey:'tick_window_seconds', type:'number', step:10, min:10, max:300 },
  { id:'entry_start_time',         group:'進場條件', label:'進場開始時間',           desc:'此時間之前不開新倉（例：09:15 = 開盤後觀察15分鐘再進場）', unit:'HH:MM', rtKey:'entry_start_time', type:'time' },
  { id:'max_change_pct',           group:'進場條件', label:'最大漲跌幅',             desc:'個股當日漲跌幅（絕對值）超過此%不進場，避免追高或跌太多', unit:'%', rtKey:'max_change_pct', type:'number', step:0.5, min:0.5 },
  { id:'check_not_in_position',    group:'進場條件', label:'同標的未持倉才可進場',   desc:'勾選（預設）：同一標的已有持倉時拒絕再進場；取消勾選：允許同標的持倉中再進一張', unit:'', rtKey:'check_not_in_position', type:'boolean' },
  { id:'check_futures_signal',     group:'進場條件', label:'期貨正價差才可進場',     desc:'勾選（預設）：個股有期貨資料時，期貨價須 > 現貨才允許進場；取消勾選：忽略期貨訊號', unit:'', rtKey:'check_futures_signal', type:'boolean' },
  // 停損停利
  { id:'stop_loss_ticks',      group:'停損停利', label:'停損 tick 數',    desc:'進場後向下跌超過此 tick 數觸發停損（觸價單）；停損價 = 進場價 - N × tick_size，向上捨入', unit:'tick', rtKey:'stop_loss_ticks', type:'number', step:1, min:1 },
  { id:'take_profit_add_pct',  group:'停損停利', label:'停利附加漲幅',    desc:'停利觸價單 = 昨收 × (1 + (進場時漲幅 + 此%) / 100)，向下捨入 tick；例：進場漲4%、附加4% → 停利在昨收漲8%', unit:'%', rtKey:'take_profit_add_pct', type:'number', step:0.5, min:0.5 },
  // 交易時間
  { id:'force_exit_time',         group:'交易時間', label:'強制出場時間',  desc:'到達此時間所有持倉強制市價出清（不掛限價，直接市價）', unit:'HH:MM', rtKey:'force_exit_time', type:'time' },
  { id:'latest_dynamic_add_time', group:'交易時間', label:'進場截止時間',  desc:'此時間後不接受新進場信號，太接近收盤避免來不及出清', unit:'HH:MM', rtKey:'latest_dynamic_add_time', type:'time' },
  // 委託設定
  { id:'commission_discount', group:'委託設定', label:'手續費折扣', desc:'券商手續費折讓倍率：0.28 = 付28%，72% 月底退還', unit:'折', rtKey:'commission_discount', type:'number', step:0.01, min:0.01, max:1 },
  // 當沖篩選條件
  { id:'daytrade_price_min', group:'當沖篩選', label:'股價下限', desc:'當沖候選昨收低於此值排除（太便宜流動性差）', unit:'元', rtKey:'daytrade_price_min', type:'number', step:50, min:0 },
  { id:'daytrade_price_max', group:'當沖篩選', label:'股價上限', desc:'當沖候選昨收高於此值排除（太貴不利資金配置）', unit:'元', rtKey:'daytrade_price_max', type:'number', step:50, min:0 },
]

const _PARAM_GROUPS = Array.from(new Set(PARAM_DEFS.map(p => p.group)))

function ParamsTab() {
  const [rtParams, setRtParams] = useState<any>(null)
  const [vals, setVals] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<{ok: boolean; msg: string} | null>(null)

  useEffect(() => {
    axios.get(`${API}/trading-params`).then(r1 => {
      setRtParams(r1.data)
      const v: Record<string, any> = {}
      for (const p of PARAM_DEFS) {
        v[p.id] = r1.data[p.rtKey]
      }
      setVals(v)
    }).catch(() => {})
  }, [])

  const save = async () => {
    if (!rtParams) return
    setSaving(true); setNote(null)
    try {
      const body: Record<string, any> = { dry_run: rtParams.dry_run ?? true }
      for (const p of PARAM_DEFS) {
        if (vals[p.id] != null) body[p.rtKey] = vals[p.id]
      }
      await axios.post(`${API}/trading-params`, body)
      setNote({ ok: true, msg: '✓ 已儲存' })
    } catch (e: any) {
      setNote({ ok: false, msg: `✕ 儲存失敗：${e?.response?.data?.detail ?? e.message}` })
    } finally { setSaving(false) }
  }

  if (!rtParams)
    return <div className={`text-center py-12 text-sm ${muted}`}>載入中...</div>

  const isDry = rtParams?.dry_run ?? true

  return (
    <div className="space-y-4">
      {/* 儲存按鈕 */}
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={save} disabled={saving}
          className="px-6 py-2 bg-gradient-to-r from-blue-600 to-blue-500 text-white text-sm rounded-lg font-semibold disabled:opacity-50">
          {saving ? '儲存中...' : '儲存全部設定'}
        </button>
        <span className={`text-xs ${muted}`}>
          ⚡ <span className="text-blue-400/80">所有參數即時生效，無需重啟引擎</span>
        </span>
        {note && <span className={`text-xs font-medium ${note.ok ? 'text-green-400' : 'text-red-400'}`}>{note.msg}</span>}
      </div>

      {/* Dry Run 開關（儲存後才生效）*/}
      <div className={`${card} px-5 py-3 flex items-center justify-between`}>
        <div>
          <span className={`text-sm font-bold ${isDry ? 'text-blue-400' : 'text-red-400'}`}>
            {isDry ? '🔵 模擬模式（Dry Run）' : '🔴 實盤模式（LIVE）'}
          </span>
          {!isDry && (
            <div className="text-xs text-red-400 mt-1">⚠ 實盤模式將真實下單，請確認所有設定正確後再儲存</div>
          )}
        </div>
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

      {/* 參數清單表格 */}
      <div className={`${card} overflow-x-auto`}>
        <table className="w-full min-w-[640px]">
          <thead className="bg-[#0d1f35] border-b border-[#253d5c]">
            <tr>
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
                  <td colSpan={4} className="px-3 py-1.5">
                    <span className="text-[11px] font-bold text-[#60a5fa] tracking-widest uppercase">{group}</span>
                  </td>
                </tr>
                {PARAM_DEFS.filter(p => p.group === group).map(p => (
                  <tr key={p.id} className="border-b border-[#1a2d4a] hover:bg-[#162336] transition-colors">
                    <td className="px-3 py-2.5">
                      <div className="text-xs font-semibold text-[#dde6f0]">{p.label}</div>
                      <div className="text-[10px] mt-0.5 text-blue-400/70">⚡ 即時</div>
                    </td>
                    <td className={`px-3 py-2.5 text-xs ${muted} leading-relaxed`}>{p.desc}</td>
                    <td className="px-3 py-2.5 text-right">
                      {p.type === 'boolean' ? (
                        <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                          <div className="relative w-9 h-5">
                            <input type="checkbox" className="sr-only"
                              checked={vals[p.id] !== false}
                              onChange={e => setVals(prev => ({ ...prev, [p.id]: e.target.checked }))}
                            />
                            <div className={`w-9 h-5 rounded-full transition-colors ${vals[p.id] !== false ? 'bg-blue-500' : 'bg-[#3d5570]'}`} />
                            <div className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${vals[p.id] !== false ? 'translate-x-4' : 'translate-x-0.5'}`} />
                          </div>
                          <span className={`text-xs ${vals[p.id] !== false ? 'text-blue-400' : muted}`}>
                            {vals[p.id] !== false ? '啟用' : '停用'}
                          </span>
                        </label>
                      ) : (
                        <input
                          type={p.type === 'time' ? 'text' : 'number'}
                          value={vals[p.id] ?? ''}
                          step={p.step}
                          min={p.min}
                          max={p.max}
                          onChange={e => setVals(prev => ({
                            ...prev,
                            [p.id]: p.type === 'time' ? e.target.value : Number(e.target.value)
                          }))}
                          className={`w-24 text-right bg-[#0c1929] border border-[#253d5c] text-[#dde6f0]
                            px-2 py-1 text-xs ${mono} rounded focus:outline-none focus:border-[#60a5fa]`}
                        />
                      )}
                    </td>
                    <td className={`px-3 py-2.5 text-xs ${muted}`}>{p.unit}</td>
                  </tr>
                ))}
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
  const connSettings = {
    apiUrl: '/fubon-api',
    dailyDb: '/fubon-data/daily.db',
    ticksDb: '/fubon-data/ticks.db',
  }

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
  const fubon = cfg?.fubon ?? {}
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
        <div className={`${card} p-5 space-y-4`}>
          {[
            { label: 'FastAPI URL（reverse proxy 固定）', value: connSettings.apiUrl },
            { label: 'daily.db 路徑（後端啟動參數決定）', value: connSettings.dailyDb },
            { label: 'ticks.db 路徑（後端啟動參數決定）', value: connSettings.ticksDb },
          ].map(row => (
            <div key={row.label}>
              <div className={`text-xs ${muted} mb-1`}>{row.label}</div>
              <div className={`bg-[#0c1929] border border-[#253d5c] text-[#6b84a0] rounded-lg px-3 py-2 text-sm ${mono} select-all`}>
                {row.value}
              </div>
            </div>
          ))}
          <div className={`text-xs ${muted}`}>
            連線路徑由 nginx reverse proxy 固定，資料庫路徑由後端啟動參數設定，無法在此修改。
          </div>
        </div>
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
      const lineSent = r.data.sent === true
      setMsg({ ok: lineSent, text: lineSent ? `✓ 模擬買入 ${symbol}，LINE 已送出` : `✓ 模擬買入 ${symbol}（LINE 未送出，請確認 token 設定）` })
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
      const lineSentS = r.data.sent === true
      setMsg({ ok: true, text: `✓ 模擬出場 ${symbol}，損益 ${r.data.pnl >= 0 ? '+' : ''}${r.data.pnl.toLocaleString()}${lineSentS ? '，LINE 已送出' : '（LINE 未送出）'}` })
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
              持倉：{simPos.symbol} @ {simPos.entry_price}  停損={simPos.stop_loss?.toFixed(2)}  停利={simPos.take_profit?.toFixed(2)}  張={simPos.lots}
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

// ── 訊息 Log Tab ──────────────────────────────────────────────────────────────
const MSG_TYPE_LABEL: Record<string, string> = {
  auto_entry:  '自動進場',
  auto_exit:   '自動出場',
  dry_entry:   'DRY進場',
  dry_exit:    'DRY出場',
  warning:     '預警',
  force_exit:  '強制出場',
  debug:       '模擬測試',
  general:     '通知',
}

function LineLogTab() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    axios.get(`${API}/line-notifications?days=5&limit=200`)
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15_000)
    return () => clearInterval(t)
  }, [])

  const rows: any[] = data?.rows ?? []

  const fmtTime = (s: string) => {
    try {
      const d = new Date(s)
      return d.toLocaleString('zh-TW', { timeZone: 'Asia/Taipei', hour12: false,
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch { return s }
  }

  const typeColor = (t: string) =>
    t === 'auto_entry'  ? 'text-green-400' :
    t === 'auto_exit'   ? 'text-blue-400' :
    t === 'force_exit'  ? 'text-red-400' :
    t === 'warning'     ? 'text-yellow-400' :
    t === 'debug'       ? 'text-purple-400' : muted

  return (
    <div className="space-y-4">
      {/* 額度摘要 */}
      <div className={`${card} px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-sm`}>
        <span className={muted}>本月已送</span>
        <span className={`${mono} font-bold text-[#dde6f0]`}>{data?.total_sent ?? '–'} 則</span>
        <span className={`border-l border-[#253d5c] pl-4 ${muted}`}>剩餘額度</span>
        <span className={`${mono} font-bold ${(data?.free_remaining ?? 200) <= 20 ? 'text-red-400' : 'text-green-400'}`}>
          {data?.free_remaining ?? '–'} / 200
        </span>
        <span className={`${muted} text-xs`}>(LINE free plan 每月 200 則)</span>
        <button onClick={load} disabled={loading}
          className={`ml-auto px-3 py-1 rounded text-xs border border-[#253d5c] ${muted} hover:text-[#dde6f0] disabled:opacity-40`}>
          {loading ? '載入中...' : '重新整理'}
        </button>
      </div>

      {/* 記錄表格 */}
      <div id="line-log-table" className={card}>
        <div className={`px-4 py-2 border-b border-[#253d5c] text-xs ${muted} flex items-center gap-3`}>
          <span>近 5 天通知記錄（共 {rows.length} 筆）</span>
          <span className="text-[#4a9f6e]">● 每 15 秒自動更新</span>
        </div>
        {loading && rows.length === 0 ? (
          <div className={`text-center py-10 text-sm ${muted}`}>載入中...</div>
        ) : rows.length === 0 ? (
          <div className={`text-center py-10 text-sm ${muted}`}>近 5 天無通知記錄</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className={`${muted} border-b border-[#253d5c]`}>
                  <th className="px-3 py-2 text-left whitespace-nowrap">時間</th>
                  <th className="px-3 py-2 text-left whitespace-nowrap">類型</th>
                  <th className="px-3 py-2 text-center whitespace-nowrap">第 N 次</th>
                  <th className="px-3 py-2 text-left">訊息內容</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: any, i: number) => (
                  <tr key={i} className="border-b border-[#1a2d4a] hover:bg-[#1a2d4a]/40">
                    <td className={`px-3 py-2 ${mono} whitespace-nowrap ${muted}`}>{fmtTime(r.sent_at)}</td>
                    <td className={`px-3 py-2 font-semibold whitespace-nowrap ${typeColor(r.msg_type)}`}>
                      {MSG_TYPE_LABEL[r.msg_type] ?? r.msg_type}
                    </td>
                    <td className={`px-3 py-2 text-center ${mono} ${muted}`}>
                      {r.monthly_seq > 0 ? `#${r.monthly_seq}` : '–'}
                    </td>
                    <td className="px-3 py-2 text-[#dde6f0] max-w-sm">
                      <div className="truncate" title={r.content}>{r.content.replace(/\n/g, ' ｜ ')}</div>
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
        {sub === 'manual'      && <ManualTradeContent />}
        {sub === 'trades'      && <TradesTab />}
        {sub === 'pre-session' && <PreSessionTab />}
        {sub === 'params'      && <ParamsTab />}
        {sub === 'config'      && <ConfigTab />}
        {sub === 'health'      && <HealthTab />}
        {sub === 'line-log'    && <LineLogTab />}
      </div>
    </div>
  )
}
