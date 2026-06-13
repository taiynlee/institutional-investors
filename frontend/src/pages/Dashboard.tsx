import { useScreener } from '../hooks/useScreener'
import { StockCard } from '../components/StockCard'
import type { JobStatus, ScreenerResult } from '../types'
import { useEffect, useState } from 'react'

interface AIPick { calc_date: string | null; code: string | null; name: string | null; reason: string | null }

function useAIPick() {
  const [pick, setPick] = useState<AIPick | null>(null)
  useEffect(() => {
    fetch('/api/ai-pick').then(r => r.json()).then(setPick).catch(() => {})
  }, [])
  return pick
}

function useFallbackScores() {
  const [topA, setTopA] = useState<ScreenerResult[]>([])
  const [topB, setTopB] = useState<ScreenerResult[]>([])
  const load = () => {
    fetch('/api/score-a').then(r => r.json()).then((d: ScreenerResult[]) => setTopA(d.slice(0, 5))).catch(() => {})
    fetch('/api/score-b').then(r => r.json()).then((d: ScreenerResult[]) => setTopB(d.slice(0, 5))).catch(() => {})
  }
  return { topA, topB, load }
}

function FallbackTable({ title, stocks, scoreKey, onResearchStock }: {
  title: string
  stocks: ScreenerResult[]
  scoreKey: 'score_a' | 'score_b'
  onResearchStock?: (code: string) => void
}) {
  if (stocks.length === 0) return null
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-gray-300">{title} Top 5</span>
        <span className="text-xs text-gray-500 ml-2">今日無突破訊號，列出候補</span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-gray-500 text-xs border-b border-gray-800">
            <th className="px-4 py-2 text-left">代碼</th>
            <th className="px-4 py-2 text-left">名稱</th>
            <th className="px-4 py-2 text-right">分數</th>
            <th className="px-4 py-2 text-right">BB位</th>
            <th className="px-4 py-2 text-right">籌碼6d%</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map(s => (
            <tr key={s.code} className="border-b border-gray-800 hover:bg-gray-800">
              <td
                className="px-4 py-2 font-mono text-blue-300 font-bold cursor-pointer hover:text-blue-400"
                onClick={() => onResearchStock?.(s.code)}
              >{s.code}</td>
              <td className="px-4 py-2 text-white">{s.name}</td>
              <td className="px-4 py-2 text-right text-yellow-400 font-bold">{s[scoreKey]?.toFixed(1)}</td>
              <td className="px-4 py-2 text-right text-gray-300">{s.bb_position?.toFixed(1)}</td>
              <td className={`px-4 py-2 text-right font-mono ${(s.chip_ratio_6d ?? 0) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                {s.chip_ratio_6d != null ? `${s.chip_ratio_6d >= 0 ? '+' : ''}${s.chip_ratio_6d.toFixed(2)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function JobStatusBadge({ job }: { job: JobStatus }) {
  const done = job.status === 'success'
  const failed = job.status === 'failed'
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[72px]">
      <span className="text-xs text-gray-400 font-medium">{job.name}</span>
      <span className="text-[10px] text-gray-600">{job.schedule}</span>
      {done ? (
        <span className="text-[10px] text-green-400">✓ {job.updated_at ?? ''}</span>
      ) : failed ? (
        <span className="text-[10px] text-red-400">✗ 失敗</span>
      ) : (
        <span className="text-[10px] text-gray-600">等待中</span>
      )}
    </div>
  )
}

export function Dashboard({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const { results, status, loading } = useScreener()
  const pick = useAIPick()
  const { topA, topB, load: loadFallback } = useFallbackScores()

  useEffect(() => {
    if (!loading && results.length === 0) loadFallback()
  }, [loading, results.length])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">台股電子股主力篩選</h1>
            <p className="text-gray-400 text-sm">策略 A: 突破籌碼好　策略 B: 創高後拉回、主力未出場　策略 C: 基本面加速</p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${status?.is_reliable ? 'text-green-400' : 'text-yellow-400'}`}>
              {status?.is_reliable ? '資料完整' : '資料更新中'}
            </div>
            <div className="text-xs text-gray-500">{status?.date} 21:00 後可信</div>
          </div>
        </div>

        {status && (
          <div className="mb-6 p-4 bg-gray-900 rounded-lg">
            <div className="flex gap-4 flex-wrap items-center">
              {/* AI精選 */}
              {pick?.code ? (() => {
                const rank1 = results[0]
                const sameStock = rank1 && rank1.code === pick.code
                const tipLines: string[] = sameStock
                  ? [
                      `分數排名第一，同時也是 AI 精選第一。`,
                      `${pick.code} ${pick.name} 在量化評分與 AI 綜合判斷上雙料第一。`,
                      `精選理由：${pick.reason}`,
                    ]
                  : [
                      `分數排名第一：${rank1?.code ?? ''} ${rank1?.name ?? ''}（B分 ${rank1?.score_b ?? ''}，策略 ${rank1?.tags?.join('+') ?? ''}）`,
                      `AI 精選第一：${pick.code} ${pick.name}`,
                      ``,
                      `精選理由：${pick.reason}`,
                      ``,
                      `為何排名第一不是精選第一？`,
                      `AI 不以量化分數排序，而是綜合策略解讀、籌碼質量與洗盤訊號進行判斷。`,
                      `分數最高代表「量化條件最達標」；AI 精選代表「最值得關注的入場機會」，兩者視角不同。`,
                    ]
                const tip = tipLines.join('\n')
                return (
                  <div className="relative group shrink-0">
                    <div
                      className="flex flex-col items-center gap-0.5 cursor-pointer select-none"
                      onClick={() => navigator.clipboard.writeText(tip)}
                      title="點擊複製"
                    >
                      <span className="text-sm text-blue-300 font-semibold">AI 精選</span>
                      <span className="text-sm text-white font-bold whitespace-nowrap">{pick.code} {pick.name} <span className="text-blue-400 opacity-50 text-xs">⎘</span></span>
                    </div>
                    <div className="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity
                      absolute z-50 top-full left-0 mt-2 w-[420px]
                      text-[11px] leading-relaxed bg-gray-950 border border-blue-500
                      text-gray-200 rounded-lg p-3 shadow-2xl pointer-events-auto whitespace-pre-wrap select-text">
                      {tip}
                      <div
                        className="mt-2 pt-2 border-t border-blue-800 text-blue-400 text-[10px] cursor-pointer hover:text-blue-300"
                        onClick={() => navigator.clipboard.writeText(tip)}
                      >
                        點擊複製全文
                      </div>
                    </div>
                  </div>
                )
              })() : (
                <div className="flex flex-col items-center gap-0.5 shrink-0">
                  <span className="text-sm text-gray-500 font-semibold">AI 精選</span>
                  <span className="text-sm text-gray-600">—</span>
                </div>
              )}
              <div className="w-px h-8 bg-gray-700 shrink-0" />
              {/* Job badges */}
              <div className="flex gap-6 flex-wrap flex-1">
                {status.jobs.map(job => (
                  <JobStatusBadge key={job.name} job={job} />
                ))}
              </div>
              <span className="text-xs text-gray-500 self-center shrink-0">篩出 {results.length} 檔</span>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="space-y-4">
            <p className="text-gray-500 text-sm text-center py-4">今日無符合突破條件的股票，以下列出策略A/B候補名單</p>
            <FallbackTable title="策略A 最高分" stocks={topA} scoreKey="score_a" onResearchStock={onResearchStock} />
            <FallbackTable title="策略B 最高分" stocks={topB} scoreKey="score_b" onResearchStock={onResearchStock} />
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(stock => <StockCard key={stock.code} stock={stock} onResearchStock={onResearchStock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
