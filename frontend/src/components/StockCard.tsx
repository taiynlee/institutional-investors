import type { ScreenerResult } from '../types'
import { BBGauge } from './BBGauge'
import { ChipBar } from './ChipBar'

interface StockCardProps { stock: ScreenerResult }

export function StockCard({ stock }: StockCardProps) {
  const scoreColor =
    stock.score >= 80 ? 'text-green-400' : 'text-yellow-400'

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-blue-500 transition-colors">
      <div className="flex justify-between items-start mb-3">
        <div>
          <span className="text-white font-bold text-lg">{stock.code}</span>
          <span className="text-gray-400 text-sm ml-2">{stock.name}</span>
        </div>
        <div className={`text-2xl font-black ${scoreColor}`}>{stock.score}</div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {stock.tags.filter(t => ['A', 'B', 'A+B'].includes(t)).map(tag => (
          <span key={tag} className="px-2 py-0.5 bg-green-900 text-green-300 text-xs rounded-full font-semibold">策略 {tag}</span>
        ))}
        {stock.is_squeeze && (
          <span className="px-2 py-0.5 bg-purple-900 text-purple-300 text-xs rounded-full">盤整</span>
        )}
      </div>

      <BBGauge position={stock.bb_position} />

      <div className="text-xs text-gray-500 text-center mt-1">
        創高位階 {stock.bb_peak.toFixed(1)} | 量比 {stock.vol_ratio.toFixed(2)}
      </div>

      <ChipBar stock={stock} />
    </div>
  )
}
