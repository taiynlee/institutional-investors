import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ScoreCResult } from '../types'

function EpsBar({ eps }: { eps: number | null }) {
  if (eps === null) return <div className="text-[10px] text-gray-600">—</div>
  const color = eps > 0 ? 'text-green-400' : 'text-red-400'
  return <div className={`text-xs font-bold ${color}`}>{eps.toFixed(2)}</div>
}

function ScoreCCard({ r, onResearchStock }: { r: ScoreCResult; onResearchStock?: (code: string) => void }) {
  const scoreColor = r.score_c >= 70 ? 'text-green-400' : r.score_c >= 50 ? 'text-yellow-400' : 'text-orange-400'
  const yoyColor = r.rev_yoy >= 50 ? 'text-red-400' : r.rev_yoy >= 30 ? 'text-orange-400' : r.rev_yoy >= 10 ? 'text-yellow-400' : 'text-gray-400'
  const momColor = r.rev_mom >= 10 ? 'text-red-400' : r.rev_mom >= 5 ? 'text-orange-400' : r.rev_mom >= 0 ? 'text-yellow-400' : 'text-gray-500'

  const yoyLabel = r.rev_yoy >= 0 ? `+${r.rev_yoy.toFixed(1)}%` : `${r.rev_yoy.toFixed(1)}%`
  const momLabel = r.rev_mom >= 0 ? `+${r.rev_mom.toFixed(1)}%` : `${r.rev_mom.toFixed(1)}%`

  const hasEps = r.eps_q1 !== null || r.eps_q2 !== null

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-yellow-500 transition-colors">
      <div className="flex justify-between items-start mb-3">
        <div>
          <span
            className="text-white font-bold text-lg cursor-pointer hover:text-yellow-400"
            onClick={() => onResearchStock?.(r.code)}
          >{r.code}</span>
          <span className="text-gray-400 ml-2">{r.name}</span>
          <span className="text-[10px] text-gray-600 ml-2">{r.calc_date.slice(5)}</span>
        </div>
        <div className="text-right">
          <div className={`text-3xl font-black ${scoreColor}`}>{r.score_c}</div>
          <div className="text-[10px] text-gray-500">策略C</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        <span className="px-2 py-0.5 text-xs rounded-full font-semibold bg-yellow-900 text-yellow-300">基本面</span>
        {r.rev_yoy >= 30 && (
          <span className="px-2 py-0.5 text-xs rounded-full bg-red-900 text-red-300">YoY爆發</span>
        )}
        <span className="px-2 py-0.5 text-xs rounded-full bg-gray-800 text-gray-400">
          {r.rev_year}/{r.rev_month.toString().padStart(2, '0')}月營收
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-3 text-xs">
        <div className="bg-gray-800 rounded p-2 text-center">
          <div className={`font-bold text-base ${yoyColor}`}>{yoyLabel}</div>
          <div className="text-gray-500">YoY 年增率</div>
        </div>
        <div className="bg-gray-800 rounded p-2 text-center">
          <div className={`font-bold text-base ${momColor}`}>{momLabel}</div>
          <div className="text-gray-500">MoM 月增率</div>
        </div>
      </div>

      {hasEps && (
        <div className="bg-gray-800 rounded p-2">
          <div className="text-xs text-gray-500 mb-1">近4季EPS（最新→較早）</div>
          <div className="grid grid-cols-4 gap-1">
            {[
              { eps: r.eps_q1, label: '最近' },
              { eps: r.eps_q2, label: '前1季' },
              { eps: r.eps_q3, label: '前2季' },
              { eps: r.eps_q4, label: '前3季' },
            ].map(({ eps, label }) => (
              <div key={label} className="text-center">
                <EpsBar eps={eps} />
                <div className="text-[10px] text-gray-600">{label}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function ScoreC({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [results, setResults] = useState<ScoreCResult[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get<ScoreCResult[]>('/api/score-c')
      .then(r => setResults(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">策略C：基本面加速</h1>
          <p className="text-gray-400 text-sm">月營收YoY≥10% + 連2月YoY加速 + 近2季EPS&gt;0</p>
          <p className="text-gray-500 text-xs mt-1">YoY幅度25分 / 連加速15分 / MoM15分 / EPS QoQ 30分 / TTM YoY 15分</p>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無策略C股票</div>
        ) : (
          <>
            <div className="text-gray-500 text-xs mb-4">{results.length} 檔通過篩選</div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {results.map(r => <ScoreCCard key={r.code} r={r} onResearchStock={onResearchStock} />)}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
