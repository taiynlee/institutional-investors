import { useEffect, useState } from 'react'
import axios from 'axios'
import type { ScreenerResult } from '../types'
import { BBGauge } from '../components/BBGauge'
import { ChipBar } from '../components/ChipBar'

function ScoreBCard({ stock, onResearchStock }: { stock: ScreenerResult; onResearchStock?: (code: string) => void }) {
  const score = stock.score_b
  const scoreColor = score >= 80 ? 'text-green-400' : score >= 60 ? 'text-yellow-400' : 'text-orange-400'

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-blue-500 transition-colors">
      <div className="flex justify-between items-start mb-3">
        <div>
          <span
            className="text-white font-bold text-lg cursor-pointer hover:text-blue-400"
            onClick={() => onResearchStock?.(stock.code)}
          >{stock.code}</span>
          <span className="text-gray-400 ml-2">{stock.name}</span>
          <span className="text-[10px] text-gray-600 ml-2">{stock.calc_date.slice(5)}</span>
        </div>
        <div className="text-right">
          <div className={`text-3xl font-black ${scoreColor}`}>{score.toFixed(0)}</div>
          <div className="text-[10px] text-gray-500">策略B</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {stock.tags.includes('A+B')
          ? <span className="px-2 py-0.5 text-xs rounded-full font-semibold bg-blue-900 text-blue-300">A+B</span>
          : <span className="px-2 py-0.5 text-xs rounded-full font-semibold bg-blue-900 text-blue-300">策略B</span>
        }
        {stock.is_squeeze && (
          <span className="px-2 py-0.5 bg-teal-900 text-teal-300 text-xs rounded-full">盤整⚡</span>
        )}
        {stock.streak >= 2 && (
          <span className="px-2 py-0.5 bg-purple-900 text-purple-300 text-xs rounded-full">連{stock.streak}日</span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3 text-xs text-center">
        <div>
          <div className="text-blue-300 font-bold">{stock.bb_peak.toFixed(1)}</div>
          <div className="text-gray-500">突破位階</div>
        </div>
        <div>
          <div className="text-yellow-300 font-bold">{stock.peak_days_ago}日</div>
          <div className="text-gray-500">創高後天數</div>
        </div>
        <div>
          <div className={`font-bold ${stock.dip_bonus > 0 ? 'text-orange-400' : 'text-gray-500'}`}>
            +{stock.dip_bonus}
          </div>
          <div className="text-gray-500">逆勢買超</div>
        </div>
      </div>

      <BBGauge position={stock.bb_position} />

      <div className="text-xs text-gray-500 text-center mt-1">
        <span>BB位階 {stock.bb_position.toFixed(1)}</span>
        <span className="mx-2">|</span>
        <span>量比 {stock.vol_ratio.toFixed(2)}</span>
        {stock.volume != null && stock.volume > 0 && (
          <>
            <span className="mx-2">|</span>
            <span className="text-blue-400">{(stock.volume / 1000).toFixed(0)}K張</span>
          </>
        )}
        {stock.holders_bonus !== 0 && (
          <>
            <span className="mx-2">|</span>
            <span className={stock.holders_bonus > 0 ? 'text-sky-400' : 'text-pink-400'}>
              大戶{stock.holders_bonus > 0 ? '+' : ''}{stock.holders_bonus?.toFixed(2)}%
            </span>
          </>
        )}
      </div>

      <ChipBar stock={stock} />
    </div>
  )
}

export function ScoreB({ onResearchStock }: { onResearchStock?: (code: string) => void }) {
  const [results, setResults] = useState<ScreenerResult[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get<ScreenerResult[]>('/api/score-b')
      .then(r => setResults(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-black text-white">策略B：籌碼拉回評分</h1>
          <p className="text-gray-400 text-sm">50日內創30日新高後，BB拉回≤5，法人6日+12日均持續買超</p>
          <p className="text-gray-500 text-xs mt-1">BB壓縮+35分 / 籌碼強度+30分 / 洗盤深度+20分 / 大戶+15分</p>
        </div>

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無策略B股票</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(s => <ScoreBCard key={s.code} stock={s} onResearchStock={onResearchStock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
