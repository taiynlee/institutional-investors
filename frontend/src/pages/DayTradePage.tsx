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

// ── Today's live trading ─────────────────────────────────────────────────────
function LiveTab() {
  const [positions, setPositions] = useState<any[]>([])
  const [status, setStatus] = useState<{ total_pnl: number; trade_count: number } | null>(null)
  const [ticks, setTicks] = useState<Record<string, any>>({})
  const evsRef = useRef<EventSource | null>(null)

  useEffect(() => {
    const loadPositions = () => {
      axios.get(`${API}/positions`).then(r => setPositions(r.data)).catch(() => {})
    }
    const loadStatus = () => {
      axios.get(`${API}/status`).then(r => setStatus(r.data)).catch(() => {})
    }
    loadPositions()
    loadStatus()
    const t = setInterval(() => { loadPositions(); loadStatus() }, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const syms = positions.map(p => p.symbol).join(',')
    if (evsRef.current) evsRef.current.close()
    if (!syms) return
    const evs = new EventSource(`${API}/stream?syms=${syms}`)
    evs.onmessage = e => {
      try { setTicks(JSON.parse(e.data)) } catch {}
    }
    evsRef.current = evs
    return () => evs.close()
  }, [positions.map(p => p.symbol).join(',')])

  const pnlColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-gray-400'

  return (
    <div className="space-y-4">
      {/* PnL summary */}
      {status && (
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <div className="text-gray-500 text-xs mb-1">今日損益</div>
            <div className={`text-2xl font-bold font-mono ${pnlColor(status.total_pnl)}`}>
              {status.total_pnl >= 0 ? '+' : ''}{status.total_pnl.toLocaleString()}
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
            <div className="text-gray-500 text-xs mb-1">成交筆數</div>
            <div className="text-2xl font-bold text-white">{status.trade_count}</div>
          </div>
        </div>
      )}

      {/* Positions */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-4 py-2 border-b border-gray-800 text-xs text-gray-500 font-medium">持倉</div>
        {positions.length === 0 ? (
          <div className="text-center text-gray-600 py-8 text-sm">無持倉</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 text-xs border-b border-gray-800">
                <th className="px-4 py-2 text-left">代號</th>
                <th className="px-4 py-2 text-right">張數</th>
                <th className="px-4 py-2 text-right">成本</th>
                <th className="px-4 py-2 text-right">現價</th>
                <th className="px-4 py-2 text-right">停損</th>
                <th className="px-4 py-2 text-right">未實現</th>
              </tr>
            </thead>
            <tbody>
              {positions.map(p => {
                const tick = ticks[p.symbol]
                const cur = tick?.price ?? null
                const unreal = cur != null ? (cur - p.entry_price) * p.lots * 1000 : null
                return (
                  <tr key={p.symbol} className="border-b border-gray-800 hover:bg-gray-800">
                    <td className="px-4 py-2 font-mono text-blue-300 font-bold">{p.symbol}</td>
                    <td className="px-4 py-2 text-right text-white">{p.lots}</td>
                    <td className="px-4 py-2 text-right font-mono text-gray-300">{p.entry_price?.toFixed(1)}</td>
                    <td className="px-4 py-2 text-right font-mono text-white">
                      {cur != null ? cur.toFixed(1) : '—'}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-orange-400">{p.stop_loss?.toFixed(1)}</td>
                    <td className={`px-4 py-2 text-right font-mono ${unreal != null ? pnlColor(unreal) : 'text-gray-600'}`}>
                      {unreal != null ? `${unreal >= 0 ? '+' : ''}${unreal.toLocaleString()}` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Trade history ────────────────────────────────────────────────────────────
function TradesTab() {
  const [trades, setTrades] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get(`${API}/trades`).then(r => setTrades(r.data)).catch(() => {}).finally(() => setLoading(false))
  }, [])

  const pnlColor = (v: number) => v > 0 ? 'text-red-400' : v < 0 ? 'text-green-400' : 'text-gray-400'

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-2 border-b border-gray-800 text-xs text-gray-500 font-medium">今日成交紀錄</div>
      {loading ? (
        <div className="text-center text-gray-600 py-8 text-sm">載入中...</div>
      ) : trades.length === 0 ? (
        <div className="text-center text-gray-600 py-8 text-sm">今日尚無成交</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 text-xs border-b border-gray-800">
              <th className="px-4 py-2 text-left">時間</th>
              <th className="px-4 py-2 text-left">代號</th>
              <th className="px-4 py-2 text-right">張數</th>
              <th className="px-4 py-2 text-right">損益</th>
              <th className="px-4 py-2 text-right">累計損益</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i} className="border-b border-gray-800 hover:bg-gray-800">
                <td className="px-4 py-2 font-mono text-gray-400 text-xs">{t.time}</td>
                <td className="px-4 py-2 font-mono text-blue-300 font-bold">{t.symbol}</td>
                <td className="px-4 py-2 text-right text-gray-300">{t.lots}</td>
                <td className={`px-4 py-2 text-right font-mono ${pnlColor(t.pnl)}`}>
                  {t.pnl >= 0 ? '+' : ''}{t.pnl?.toLocaleString()}
                </td>
                <td className={`px-4 py-2 text-right font-mono ${pnlColor(t.cumulative_pnl)}`}>
                  {t.cumulative_pnl >= 0 ? '+' : ''}{t.cumulative_pnl?.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Pre-session logs ─────────────────────────────────────────────────────────
function PreSessionTab() {
  const [logs, setLogs] = useState<any[]>([])

  useEffect(() => {
    axios.get(`${API}/pre-session/logs`).then(r => setLogs(r.data)).catch(() => {})
  }, [])

  const statusColor = (s: string) =>
    s === 'ok' ? 'text-green-400' : s === 'running' ? 'text-yellow-400' : 'text-red-400'

  return (
    <div className="space-y-3">
      {logs.length === 0 ? (
        <div className="text-center text-gray-600 py-8 text-sm">無盤前記錄</div>
      ) : logs.map(log => (
        <div key={log.id} className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-white font-medium">{log.run_date}</span>
            <span className={`text-sm font-bold ${statusColor(log.status)}`}>{log.status}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs text-gray-400">
            <span>開始：{log.started_at}</span>
            <span>結束：{log.finished_at || '—'}</span>
            <span>總數：{log.total_stocks} 檔</span>
            <span>成功：{log.success_stocks} 檔</span>
          </div>
          {log.error_msg && <div className="mt-2 text-xs text-red-400">{log.error_msg}</div>}
        </div>
      ))}
    </div>
  )
}

// ── Trading params ───────────────────────────────────────────────────────────
function ParamsTab() {
  const [params, setParams] = useState<any>(null)
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  useEffect(() => {
    axios.get(`${API}/trading-params`).then(r => setParams(r.data)).catch(() => {})
  }, [])

  const save = () => {
    setSaving(true)
    axios.post(`${API}/trading-params`, params)
      .then(r => setNote(r.data.note || '已更新'))
      .catch(() => setNote('更新失敗'))
      .finally(() => setSaving(false))
  }

  if (!params) return <div className="text-center text-gray-600 py-8 text-sm">載入中...</div>

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-4 max-w-lg">
      <div>
        <label className="text-gray-400 text-xs block mb-1">單檔最大資金 (TWD)</label>
        <input
          type="number"
          value={params.max_position_capital}
          onChange={e => setParams({ ...params, max_position_capital: +e.target.value })}
          className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm border border-gray-700 focus:outline-none"
        />
      </div>
      <div>
        <label className="text-gray-400 text-xs block mb-1">最大同時持倉數</label>
        <input
          type="number"
          value={params.max_daily_positions}
          onChange={e => setParams({ ...params, max_daily_positions: +e.target.value })}
          className="w-full bg-gray-800 text-white rounded px-3 py-2 text-sm border border-gray-700 focus:outline-none"
        />
      </div>
      <div className="flex items-center gap-2">
        <input
          type="checkbox"
          id="dry-run"
          checked={params.dry_run}
          onChange={e => setParams({ ...params, dry_run: e.target.checked })}
          className="w-4 h-4"
        />
        <label htmlFor="dry-run" className="text-gray-300 text-sm">Dry Run（模擬模式）</label>
      </div>
      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white text-sm rounded"
      >
        {saving ? '儲存中...' : '儲存'}
      </button>
      {note && <div className="text-yellow-400 text-xs">{note}</div>}
    </div>
  )
}

// ── System config ────────────────────────────────────────────────────────────
function ConfigTab() {
  const [cfg, setCfg] = useState<any>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    axios.get(`${API}/config`).then(r => setCfg(r.data)).catch(e => setErr(e.message))
  }, [])

  if (err) return <div className="text-red-400 text-sm py-4">{err}</div>
  if (!cfg) return <div className="text-center text-gray-600 py-8 text-sm">載入中...</div>

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <pre className="text-xs text-gray-300 overflow-auto whitespace-pre-wrap font-mono leading-5">
        {JSON.stringify(cfg, null, 2)}
      </pre>
    </div>
  )
}

// ── System health ────────────────────────────────────────────────────────────
function HealthTab() {
  const [health, setHealth] = useState<any>(null)
  const [status, setStatus] = useState<any>(null)
  const [logs, setLogs] = useState<string[]>([])

  useEffect(() => {
    axios.get(`${API}/health`).then(r => setHealth(r.data)).catch(() => setHealth({ status: 'error' }))
    axios.get(`${API}/status`).then(r => setStatus(r.data)).catch(() => {})
    axios.get(`${API}/logs/today?lines=50`).then(r => setLogs(r.data.lines || [])).catch(() => {})
  }, [])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-gray-500 text-xs mb-1">Dashboard API</div>
          <div className={`font-bold ${health?.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
            {health?.status ?? '—'}
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div className="text-gray-500 text-xs mb-1">今日成交</div>
          <div className="font-bold text-white">{status?.trade_count ?? '—'} 筆</div>
        </div>
      </div>

      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-4 py-2 border-b border-gray-800 text-xs text-gray-500 font-medium">
          今日 Log（最後 50 行）
        </div>
        <div className="p-3 overflow-auto max-h-96">
          {logs.length === 0 ? (
            <div className="text-gray-600 text-xs">無 log 或引擎未啟動</div>
          ) : (
            <pre className="text-xs text-gray-400 font-mono leading-4 whitespace-pre-wrap">
              {logs.join('\n')}
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
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-5xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">台股當沖</h1>
          <p className="text-gray-500 text-sm mt-0.5">富邦證券自動交易系統</p>
        </div>

        {/* Sub-tab bar */}
        <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1 border border-gray-800 w-fit">
          {SUB_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setSub(t.id)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                sub === t.id
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
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
