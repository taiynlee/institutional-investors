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
  tech: 'bg-red-900 text-red-300',
  momentum: 'bg-orange-900 text-orange-300',
  chip: 'bg-yellow-900 text-yellow-300',
}

function ExitAlertPanel({ alerts }: { alerts: ExitAlert[] }) {
  return (
    <div className="p-3 bg-gray-900 border border-gray-700 rounded-lg flex-1">
      <span className="text-gray-400 text-xs font-medium uppercase tracking-wide">退場止損</span>
      {alerts.length === 0 ? (
        <span className="text-gray-600 text-sm ml-2">目前無退場訊號</span>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          {alerts.map(a => (
            <div key={a.code} className="flex items-center gap-2 flex-wrap">
              <span className="text-white font-bold text-sm">{a.code}</span>
              <span className="text-gray-400 text-xs">{a.name}</span>
              {a.triggered.map(t => (
                <span key={t.type} className={`px-2 py-0.5 rounded-full text-[11px] font-medium ${EXIT_COLORS[t.type] ?? 'bg-gray-700 text-gray-300'}`}>
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
          {pick?.code && (
            <div className="p-3 bg-blue-950 border border-blue-700 rounded-lg flex items-center gap-2 shrink-0">
              <span className="text-blue-300 text-xs font-medium uppercase tracking-wide whitespace-nowrap">AI 精選</span>
              <span className="text-white font-bold">{pick.code} {pick.name}</span>
            </div>
          )}
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
