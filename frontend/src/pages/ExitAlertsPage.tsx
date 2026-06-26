import { useEffect, useState } from 'react'
import type { ExitAlert } from '../types'

export function ExitAlertsPage({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [alerts, setAlerts] = useState<ExitAlert[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/exit-alerts')
      .then(r => r.json())
      .then(setAlerts)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">退場止損訊號</h1>
          <p className="text-gray-400 text-sm mt-1">
            曾通過篩選、現已落榜的個股 — 若仍持倉請注意停損
          </p>
          <div className="flex gap-3 mt-2 flex-wrap">
            <span className="flex items-center gap-1.5 text-xs text-gray-400">
              <span className="px-2 py-0.5 rounded border bg-yellow-900 text-yellow-300 border-yellow-700 text-[10px]">籌碼出場</span>
              近3日法人淨賣 ≤ -1.5%，12日仍流出
            </span>
          </div>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無落榜個股</div>
        ) : (
          <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-right">現 BB</th>
                  <th className="px-4 py-3 text-right">籌碼 3d%</th>
                  <th className="px-4 py-3 text-right">最後上榜</th>
                  <th className="px-4 py-3 text-right">已消失</th>
                  <th className="px-4 py-3 text-left">訊號</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map(a => (
                  <tr key={a.code} className="border-b border-gray-800 hover:bg-gray-800 transition-colors">
                    <td
                      className="px-4 py-3 font-mono text-blue-300 font-bold cursor-pointer hover:text-blue-400"
                      onClick={() => onResearchStock?.(a.code)}
                    >{a.code}</td>
                    <td className="px-4 py-3 text-white">{a.name}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300">{a.bb.toFixed(1)}</td>
                    <td className={`px-4 py-3 text-right font-mono ${
                      a.chip_3d_pct == null ? 'text-gray-600'
                      : a.chip_3d_pct >= 0 ? 'text-red-400' : 'text-green-400'
                    }`}>
                      {a.chip_3d_pct == null ? '—' : `${a.chip_3d_pct >= 0 ? '+' : ''}${a.chip_3d_pct.toFixed(2)}%`}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400 text-xs">{a.last_seen_date}</td>
                    <td className="px-4 py-3 text-right">
                      <span className={`font-mono text-xs ${
                        a.days_off === 0 ? 'text-yellow-400'
                        : a.days_off <= 2 ? 'text-orange-400'
                        : 'text-gray-500'
                      }`}>
                        {a.days_off === 0 ? '今日剛落榜' : `${a.days_off} 篩選日`}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {a.badges.length > 0
                        ? <div className="flex gap-1 flex-wrap">
                            {a.badges.map(b => (
                              <span key={b.type}
                                className="px-2 py-0.5 rounded text-[10px] font-medium border bg-yellow-900 text-yellow-300 border-yellow-700"
                              >{b.label}</span>
                            ))}
                          </div>
                        : <span className="text-gray-600 text-xs">—</span>
                      }
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
