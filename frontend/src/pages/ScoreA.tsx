import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ScreenerResult } from '../types'
import { BBGauge } from '../components/BBGauge'
import { ChipBar } from '../components/ChipBar'

function ScoreACard({ stock, onResearchStock }: { stock: ScreenerResult; onResearchStock?: (code: string) => void }) {
  const score = stock.score_a
  const scoreColor = score >= 80 ? 'text-green-400' : score >= 60 ? 'text-yellow-400' : 'text-orange-400'

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-green-500 transition-colors">
      <div className="flex justify-between items-start mb-3">
        <div>
          <span
            className="text-white font-bold text-lg cursor-pointer hover:text-green-400"
            onClick={() => onResearchStock?.(stock.code)}
          >{stock.code}</span>
          <span className="text-gray-400 ml-2">{stock.name}</span>
          <span className="text-[10px] text-gray-600 ml-2">{stock.calc_date.slice(5)}</span>
        </div>
        <div className="text-right">
          <div className={`text-3xl font-black ${scoreColor}`}>{score.toFixed(0)}</div>
          <div className="text-[10px] text-gray-500">策略A</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {stock.tags.includes('A+B')
          ? <span className="px-2 py-0.5 text-xs rounded-full font-semibold bg-green-900 text-green-300">A+B</span>
          : <span className="px-2 py-0.5 text-xs rounded-full font-semibold bg-green-900 text-green-300">策略A</span>
        }
        {stock.is_squeeze && (
          <span className="px-2 py-0.5 bg-teal-900 text-teal-300 text-xs rounded-full">盤整⚡</span>
        )}
        {stock.streak >= 2 && (
          <span className="px-2 py-0.5 bg-purple-900 text-purple-300 text-xs rounded-full">連{stock.streak}日</span>
        )}
        {(stock.ic_names ?? []).map(ic => (
          <span key={ic} className="px-2 py-0.5 bg-gray-700 text-gray-300 text-xs rounded-full">{ic}</span>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3 text-xs text-center">
        <div>
          <div className={`font-bold ${stock.change_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>
            {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct.toFixed(2)}%
          </div>
          <div className="text-gray-500">今日漲跌</div>
        </div>
        <div>
          <div className="text-blue-300 font-bold">{stock.ma5_days}日</div>
          <div className="text-gray-500">站穩MA5</div>
        </div>
        <div>
          <div className="text-yellow-300 font-bold">{stock.upper_slope.toFixed(2)}%</div>
          <div className="text-gray-500">上軌斜率</div>
        </div>
      </div>

      <BBGauge position={stock.bb_position} />
      <div className="text-xs text-gray-500 text-center mt-1">
        <span>BB位階 {stock.bb_position.toFixed(1)}</span>
        <span className="mx-2">|</span>
        <span>高點位置 {stock.close_position.toFixed(0)}%</span>
      </div>

      <div className="mt-2 text-xs text-gray-500 grid grid-cols-2 gap-1">
        <span>籌碼1日: <span className={stock.chip_ratio_1d > 0 ? 'text-red-400' : 'text-green-400'}>{stock.chip_ratio_1d.toFixed(2)}%</span></span>
        <span>籌碼12日: <span className={stock.chip_ratio_12d > 0 ? 'text-red-400' : 'text-green-400'}>{stock.chip_ratio_12d.toFixed(2)}%</span></span>
        <span>大戶W1: <span className={stock.holders_bonus > 0 ? 'text-red-400' : 'text-green-400'}>{stock.holders_bonus?.toFixed(2)}%</span></span>
        <span>量比: <span className="text-white">{stock.vol_ratio.toFixed(2)}</span></span>
      </div>

      <ChipBar stock={stock} />
    </div>
  )
}

export function ScoreA({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [results, setResults] = useState<ScreenerResult[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get<ScreenerResult[]>('/api/score-a')
      .then(r => setResults(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">策略A：突破品質評分</h1>
          <p className="text-gray-400 text-sm">放量創30日新高 + 法人同步買超 ≥1%股本，100分制綜合評分</p>
          <p className="text-gray-500 text-xs mt-1">A籌碼30分 / B突破35分 / C動能15分 / D大戶20分</p>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無策略A股票</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(s => <ScoreACard key={s.code} stock={s} onResearchStock={onResearchStock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
