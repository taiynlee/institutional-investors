import type { ScreenerResult } from '../types'

interface ChipBarProps { stock: ScreenerResult }

function ChipItem({ label, value, positive }: {
  label: string; value: string; positive: boolean
}) {
  return (
    <div className="text-center">
      <div className={`text-xs font-medium ${positive ? 'text-green-400' : 'text-red-400'}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  )
}

export function ChipBar({ stock }: ChipBarProps) {
  const fmtK = (n: number) => n > 0 ? `+${(n / 1000).toFixed(0)}K` : `${(n / 1000).toFixed(0)}K`
  const fmtLots = (n: number) => n > 0 ? `+${n.toFixed(0)}` : `${n.toFixed(0)}`
  const fmtPct = (n: number) => `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`
  return (
    <div className="grid grid-cols-5 gap-1 mt-2 p-2 bg-gray-800 rounded text-xs">
      <ChipItem label="外資6日" value={fmtK(stock.foreign_6d_net)} positive={stock.foreign_6d_net > 0} />
      <ChipItem label="投信6日" value={fmtLots(stock.trust_6d_net)} positive={stock.trust_6d_net > 0} />
      <ChipItem label="籌碼6日%" value={`${stock.chip_ratio_6d.toFixed(2)}%`} positive={stock.chip_ratio_6d > 0} />
      <ChipItem label="融資5日" value={fmtPct(stock.margin_5d_chg)} positive={stock.margin_5d_chg <= 0} />
      <ChipItem label="借券5日" value={fmtPct(stock.lending_5d_chg)} positive={stock.lending_5d_chg <= 0} />
    </div>
  )
}
