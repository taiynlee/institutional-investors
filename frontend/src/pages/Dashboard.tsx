import { useScreener } from '../hooks/useScreener'
import { StockCard } from '../components/StockCard'
import type { JobStatus, ExitAlert } from '../types'
import { useEffect, useState } from 'react'

interface AIPick { calc_date: string | null; code: string | null; name: string | null; reason: string | null }

function useAIPick() {
  const [pick, setPick] = useState<AIPick | null>(null)
  useEffect(() => {
    fetch('/api/ai-pick').then(r => r.json()).then(setPick).catch(() => {})
  }, [])
  return pick
}

function useExitAlerts() {
  const [alerts, setAlerts] = useState<ExitAlert[]>([])
  useEffect(() => {
    fetch('/api/exit-alerts').then(r => r.json()).then(setAlerts).catch(() => {})
  }, [])
  return alerts
}

const JOB_LABELS: Record<string, string> = {
  job1: '法人+價量',
  job2: '融資融券',
  job3: '大戶持股比',
  job4: '篩選完成',
}

function JobStatusBadge({ job }: { job: JobStatus }) {
  const done = job.status === 'success' && (job.rows > 0 || job.name === 'job4')
  const failed = job.status === 'failed'
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-[72px]">
      <span className="text-xs text-gray-400 font-medium">{JOB_LABELS[job.name] ?? job.name}</span>
      <span className="text-[10px] text-gray-600">{job.schedule}</span>
      {done ? (
        <span className="text-[10px] text-green-400">✓ {job.updated_at}</span>
      ) : failed ? (
        <span className="text-[10px] text-red-400">✗ 失敗</span>
      ) : (
        <span className="text-[10px] text-gray-600">等待中</span>
      )}
    </div>
  )
}

const EXIT_COLORS: Record<string, string> = {
  tech: 'bg-red-900 text-red-300 border-red-700',
  momentum: 'bg-orange-900 text-orange-300 border-orange-700',
  chip: 'bg-yellow-900 text-yellow-300 border-yellow-700',
}

function ExitAlertPanel({ alerts }: { alerts: ExitAlert[] }) {
  return (
    <div className="flex-1 p-3 bg-blue-950 border border-blue-700 rounded-lg flex items-center gap-2 min-w-0 overflow-x-auto">
      <span className="text-blue-300 text-xs font-medium uppercase tracking-wide whitespace-nowrap shrink-0">退場止損</span>
      {alerts.length === 0 ? (
        <span className="text-blue-500 text-xs">目前無退場訊號</span>
      ) : (
        <div className="flex gap-4 flex-wrap">
          {alerts.map(a => (
            <div key={a.code} className="flex items-center gap-1.5">
              <span className="text-white text-xs font-bold">{a.code}</span>
              <span className="text-blue-200 text-xs">{a.name}</span>
              {a.triggered.map(t => (
                <span key={t.type} className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${EXIT_COLORS[t.type] ?? 'bg-gray-700 text-gray-300 border-gray-600'}`}>
                  {t.label}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function Dashboard() {
  const { results, status, loading } = useScreener()
  const pick = useAIPick()
  const exitAlerts = useExitAlerts()

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">台股電子股主力篩選</h1>
            <p className="text-gray-400 text-sm">創高後拉回、主力未出場</p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${status?.is_reliable ? 'text-green-400' : 'text-yellow-400'}`}>
              {status?.is_reliable ? '資料完整' : '資料更新中'}
            </div>
            <div className="text-xs text-gray-500">{status?.date} 21:00 後可信</div>
          </div>
        </div>

        {status && (
          <div className="mb-4 p-4 bg-gray-900 rounded-lg">
            <div className="flex gap-6 flex-wrap items-start justify-between">
              <div className="flex gap-6 flex-wrap">
                {status.jobs.map(job => (
                  <JobStatusBadge key={job.name} job={job} />
                ))}
              </div>
              <span className="text-xs text-gray-500 self-center">篩出 {results.length} 檔</span>
            </div>
          </div>
        )}

        <div className="mb-6 flex gap-3">
          {pick?.code && (() => {
            const rank1 = results[0]
            const sameStock = rank1 && rank1.code === pick.code
            const tipLines: string[] = sameStock
              ? [
                  `分數排名第一，同時也是 AI 精選第一。`,
                  `${pick.code} ${pick.name} 在量化評分與 AI 綜合判斷上雙料第一。`,
                  `精選理由：${pick.reason}`,
                ]
              : [
                  `分數排名第一：${rank1?.code ?? ''} ${rank1?.name ?? ''}（基礎分 ${rank1?.score ?? ''}，策略 ${rank1?.tags?.join('+') ?? ''}）`,
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
                  className="p-3 bg-blue-950 border border-blue-700 rounded-lg flex items-center gap-2 cursor-pointer select-none"
                  onClick={() => navigator.clipboard.writeText(tip)}
                  title="點擊複製"
                >
                  <span className="text-blue-300 text-xs font-medium uppercase tracking-wide whitespace-nowrap">AI 精選</span>
                  <span className="text-white font-bold">{pick.code} {pick.name}</span>
                  <span className="text-blue-400 text-xs ml-1 opacity-60">⎘</span>
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
          })()}
          <ExitAlertPanel alerts={exitAlerts} />
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無符合條件的股票</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(stock => <StockCard key={stock.code} stock={stock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
