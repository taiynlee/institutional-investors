import { useEffect, useState } from 'react'
import type { ExitAlert } from '../types'

const EXIT_COLORS: Record<string, string> = {
  tech: 'bg-red-900 text-red-300 border-red-700',
  chip: 'bg-yellow-900 text-yellow-300 border-yellow-700',
}

const EXIT_TIPS: Record<string, string> = {
  chip: '近3日外資+投信淨賣 ≤ -1.5%，且12日仍持續流出',
  tech: '歷史高點 BB ≥ 75，但現在 BB < 40，已從強勢高點跌破中線',
}

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
          <div className="flex gap-3 mt-2 flex-wrap">
            <span className="flex items-center gap-1.5 text-xs text-gray-400">
              <span className="px-2 py-0.5 rounded border bg-yellow-900 text-yellow-300 border-yellow-700 text-[10px]">籌碼出場</span>
              近3日法人淨賣 ≤ -1.5%，12日仍流出
            </span>
            <span className="flex items-center gap-1.5 text-xs text-gray-400">
              <span className="px-2 py-0.5 rounded border bg-red-900 text-red-300 border-red-700 text-[10px]">跌破中線</span>
              高點 BB ≥ 75 但現在 BB &lt; 40
            </span>
          </div>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無退場訊號</div>
        ) : (
          <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-500 text-xs border-b border-gray-800">
                  <th className="px-4 py-3 text-left">代碼</th>
                  <th className="px-4 py-3 text-left">名稱</th>
                  <th className="px-4 py-3 text-right">BB位</th>
                  <th className="px-4 py-3 text-right">高點BB</th>
                  <th className="px-4 py-3 text-right">籌碼3d%</th>
                  <th className="px-4 py-3 text-left">觸發訊號</th>
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
                    <td className="px-4 py-3 text-right text-gray-300">{a.bb.toFixed(1)}</td>
                    <td className="px-4 py-3 text-right text-gray-300">{a.peak_bb.toFixed(1)}</td>
                    <td className={`px-4 py-3 text-right font-mono ${a.chip_3d_pct == null ? 'text-gray-600' : a.chip_3d_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                      {a.chip_3d_pct == null ? '—' : `${a.chip_3d_pct >= 0 ? '+' : ''}${a.chip_3d_pct.toFixed(2)}%`}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 flex-wrap">
                        {a.triggered.map(t => (
                          <span
                            key={t.type}
                            title={EXIT_TIPS[t.type] ?? ''}
                            className={`px-2 py-0.5 rounded text-[10px] font-medium border cursor-help ${EXIT_COLORS[t.type] ?? 'bg-gray-700 text-gray-300 border-gray-600'}`}
                          >
                            {t.label}
                          </span>
                        ))}
                      </div>
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
