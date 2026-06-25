import { useState } from 'react'
import { useServerClock } from './hooks/useServerTime'
import { Dashboard } from './pages/Dashboard'
import { ScoreA } from './pages/ScoreA'
import { ScoreB } from './pages/ScoreB'
import { ScoreC } from './pages/ScoreC'
import { Result } from './pages/Result'
import { SectorFlow } from './pages/SectorFlow'
import { IcChain } from './pages/IcChain'
import { Holders } from './pages/Holders'
import { WatchlistAPage } from './pages/WatchlistAPage'
import { ExitAlertsPage } from './pages/ExitAlertsPage'
import { StockResearch } from './pages/StockResearch'
import { StockPoolPage } from './pages/StockPool'
import { UsStocksPage } from './pages/UsStocksPage'
import { DayTradePage } from './pages/DayTradePage'
import { MarketHeader } from './components/MarketHeader'
import './index.css'

type Tab = 'screener' | 'score-a' | 'score-b' | 'score-c' | 'watchlist-a' | 'result' | 'exit-alerts' | 'sector' | 'ic-chain' | 'holders' | 'pool' | 'us-stocks' | 'day-trade'

const TABS: { id: Tab; label: string; sub?: string }[] = [
  { id: 'screener',    label: '篩選總覽' },
  { id: 'day-trade',   label: '台股當沖' },
  { id: 'score-a',    label: '策略A',   sub: '最新' },
  { id: 'score-b',    label: '策略B',   sub: '近3日≥60' },
  { id: 'score-c',    label: '策略C' },
  { id: 'watchlist-a',label: 'A追蹤' },
  { id: 'result',       label: '篩選績效' },
  { id: 'exit-alerts', label: '退場止損' },
  { id: 'sector',     label: '類股資金' },
  { id: 'ic-chain',   label: '產業鏈' },
  { id: 'holders',    label: '千張大戶' },
  { id: 'pool',       label: '股票池' },
  { id: 'us-stocks',  label: '美股追蹤' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('screener')
  const [researchCode, setResearchCode] = useState<string | null>(null)
  const clock = useServerClock()

  const goResearch = (code: string) => setResearchCode(code)

  return (
    <div className="min-h-screen bg-gray-950">
      <MarketHeader />
      <div className="bg-gray-900 border-b border-gray-800 px-4 py-1 flex items-center gap-1 overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`text-sm font-medium px-3 rounded whitespace-nowrap transition-colors flex flex-col items-center justify-center leading-tight h-9 ${
              tab === t.id
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-white hover:bg-gray-800'
            }`}
          >
            <span>{t.label}</span>
            {t.sub && <span className="text-[9px] text-gray-500 font-normal">{t.sub}</span>}
          </button>
        ))}
        {clock && (
          <div className="ml-auto shrink-0 flex items-center gap-1.5 px-2 py-0.5 rounded border border-gray-700 bg-gray-800">
            <span className="text-gray-500 text-[10px]">台灣</span>
            <span className="text-gray-400 text-[10px]">{clock.date}</span>
            <span className="text-white text-[11px] font-mono font-bold tabular-nums">{clock.time}</span>
          </div>
        )}
      </div>
      <div>
        {tab === 'screener'    && <Dashboard onResearchStock={goResearch} />}
        {tab === 'score-a'    && <ScoreA onResearchStock={goResearch} />}
        {tab === 'score-b'    && <ScoreB onResearchStock={goResearch} />}
        {tab === 'score-c'    && <ScoreC onResearchStock={goResearch} />}
        {tab === 'watchlist-a' && <WatchlistAPage onResearchStock={goResearch} />}
        {tab === 'result'       && <Result onResearchStock={goResearch} />}
        {tab === 'exit-alerts' && <ExitAlertsPage onResearchStock={goResearch} />}
        {tab === 'sector'     && <SectorFlow onResearchStock={goResearch} />}
        {tab === 'ic-chain'   && <IcChain onResearchStock={goResearch} />}
        {tab === 'holders'    && <Holders onResearchStock={goResearch} />}
        {tab === 'pool'       && <StockPoolPage />}
        {tab === 'us-stocks'  && <UsStocksPage />}
        {tab === 'day-trade'  && <DayTradePage />}
      </div>
      {researchCode && (
        <StockResearch code={researchCode} onClose={() => setResearchCode(null)} />
      )}
    </div>
  )
}
