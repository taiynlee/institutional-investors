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

  const screenerJob = status?.jobs?.find((j: JobStatus) => j.name === '選股篩選')
  const todayRunEmpty = screenerJob?.status === 'success' && screenerJob?.rows === 0
  const isStaleData = todayRunEmpty && results.length > 0

  useEffect(() => {
    if (!loading && (results.length === 0 || isStaleData)) loadFallback()
  }, [loading, results.length, isStaleData])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">台股電子股主力篩選</h1>
            <div className="flex flex-wrap gap-2 mt-1">
              <span
                className="cursor-help inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-900/50 text-green-300 border border-green-700/50 hover:bg-green-900/80 transition-colors"
                title={`策略 A — 剛突破籌碼好\n\n入場條件（全部同時成立）：\n① 趨勢保護：月線>季線、月線向上、季線向上、收盤>季線\n② 啟動初期：MA20斜率 0.3~2%、布林上軌斜率>2%、帶寬<35%、站上MA5≤5天（還在初期）\n③ 今日首次突破：收盤>前30日最高（昨日尚未突破）、尾盤在高低區間上70%、出量≥均量×1.5、BB位階>5\n④ 籌碼：chip_1d≥1%且chip_12d>0（或反之）\n\n評分（0~100）：籌碼強度30分（chip_1d+chip_12d）、突破品質35分（位階+收盤位置+漲幅+量比）、動能品質15分（上軌斜率+MA20斜率）、千張大戶20分`}
              >
                <span className="font-black">A</span> 剛突破籌碼好
              </span>
              <span
                className="cursor-help inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-yellow-900/50 text-yellow-300 border border-yellow-700/50 hover:bg-yellow-900/80 transition-colors"
                title={`策略 B — 創高後拉回、主力未出場\n\n入場條件（全部同時成立）：\n① 趨勢保護：月線>季線、月線向上、季線向上、收盤>季線\n② 歷史突破：近50個交易日內曾出現「收盤突破30日高且BB位階>5」的突破事件（昨日或更早，不含今日）\n③ 今日拉回：BB位階≤8（已回落至布林上軌附近或以下，算真正拉回）\n④ 主力未撤：近6日法人淨買超÷股本≥1% 且 近12日同≥1%（拉回期間持續買超）\n⑤ 大戶未跑：千張大戶本週人數持平或增加（w1≥0，主力確實未出場）\n\n評分（0~100）：BB位階(20分)+chip_6d(20分)+chip_12d(15分)+chip_20d(15分)+大戶w1/w2/w3(各10分)`}
              >
                <span className="font-black">B</span> 創高後拉回、主力未出場
              </span>
              <span
                className="cursor-help inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-900/50 text-blue-300 border border-blue-700/50 hover:bg-blue-900/80 transition-colors"
                title={`策略 C — 基本面加速\n\n完全獨立的基本面篩選，不需通過 A/B 條件：\n① 月營收 YoY ≥ 10%（年增率達標）\n② 連續 2 個月 YoY 持續加速（月增率趨勢向上）\n③ 近 2 季 EPS > 0（獲利為正）\n\n評分（0~100）：YoY幅度25分＋連加速15分＋MoM月增率15分＋EPS QoQ季增率30分＋TTM YoY年化成長15分\n\n注意：策略C與A/B完全分開，主要用於抓基本面正在加速的標的，搭配A/B技術面訊號效果最佳`}
              >
                <span className="font-black">C</span> 基本面加速
              </span>
            </div>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${status?.is_reliable ? 'text-green-400' : 'text-yellow-400'}`}>
              {status?.is_reliable ? '資料完整' : '資料更新中'}
            </div>
            <div className="text-xs text-gray-500">{status?.date} 21:10 後可信</div>
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
                {(() => {
                  const ORDER = ['法人＋股價', '融資借券', '選股篩選', '當沖篩選', '大戶持股', '月營收', '季報EPS', '產業鏈']
                  const sorted = [...status.jobs].sort((a, b) => {
                    const ai = ORDER.indexOf(a.name)
                    const bi = ORDER.indexOf(b.name)
                    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi)
                  })
                  return sorted.map(job => <JobStatusBadge key={job.name} job={job} />)
                })()}
              </div>
              <span className="text-xs text-gray-500 self-center shrink-0">
                {isStaleData ? `今日 0 支通過 (${screenerJob?.updated_at})` : `篩出 ${results.length} 檔`}
              </span>
            </div>
          </div>
        )}

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 || isStaleData ? (
          <div className="space-y-4">
            {isStaleData ? (
              <p className="text-gray-500 text-sm text-center py-4">
                今日篩選 0 支通過條件（{screenerJob?.updated_at}），以下為策略A/B候補名單（最後有效結果）
              </p>
            ) : (
              <p className="text-gray-500 text-sm text-center py-4">今日無符合突破條件的股票，以下列出策略A/B候補名單</p>
            )}
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
