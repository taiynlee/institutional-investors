import type { ScreenerResult } from '../types'
import { BBGauge } from './BBGauge'
import { ChipBar } from './ChipBar'
import { PriceSparkline } from './PriceSparkline'

function generateAnalysis(s: ScreenerResult): string {
  const lines: string[] = []

  lines.push(`${s.name} ${s.code} 解讀：`)
  lines.push('')

  const stratTags = s.tags.filter(t => ['A', 'B', 'A+B'].includes(t))
  if (stratTags.includes('A') || stratTags.includes('A+B')) {
    lines.push(`策略 A：今天放量創近30日新高，法人當天同步買超≥1%股本。主力在突破瞬間積極進場——這是帶動突破，不是散戶追漲。`)
  }
  if (stratTags.includes('B') || stratTags.includes('A+B')) {
    lines.push(`策略 B：近50交易日內曾創30日新高，今日 BB位階${s.bb_position.toFixed(1)}（≤5門檻），法人6日+12日買超均≥1%。意思是：之前主力推出去過，現在拉回到月線附近，法人沒跑。`)
    if (s.bb_peak > 0) {
      lines.push(`  ↳ 突破當天位階 ${s.bb_peak.toFixed(1)}（突破有力度）→ 今日位階 ${s.bb_position.toFixed(1)}（已充分拉回）。兩者落差越大代表洗盤越乾淨。`)
    }
    if (s.is_squeeze) {
      lines.push(`  ↳ 【盤整加成】目前布林帶寬再度收窄——股價在月線附近橫盤蓄力，是「第二次蓄力」訊號。若再度放量突破，爆發力比單純 B 訊號更強。`)
    }
  }
  if (stratTags.length > 0) lines.push('')

  const bbDesc =
    s.bb_position <= 0 ? '月線以下，已超賣' :
    s.bb_position <= 3 ? '月線附近，充分回測' :
    s.bb_position <= 5 ? '月線上方一點點，策略B標準切入點' :
    s.bb_position <= 8 ? '中段整理區' :
    s.bb_position <= 10 ? '靠近上軌，偏強勢' : '突破上軌，極強勢'
  lines.push(`BB=${s.bb_position.toFixed(1)}：布林位階${bbDesc}（0=月線，10=上軌）。`)
  lines.push('')

  const chipOk = s.chip_ratio_6d >= 1
  const fmtLots = (n: number) => Math.abs(n) >= 1000 ? `${n > 0 ? '+' : ''}${(n / 1000).toFixed(0)}K張` : `${n > 0 ? '+' : ''}${n.toFixed(0)}張`
  lines.push(`chip6d=${s.chip_ratio_6d.toFixed(2)}%：（外資${fmtLots(s.foreign_6d_net)} + 投信${fmtLots(s.trust_6d_net)}）÷ 股本 × 100% = ${s.chip_ratio_6d.toFixed(2)}%，${chipOk ? '超過入場門檻（≥1%），代表主力持續在場' : '未達入場門檻（≥1%），籌碼集中度不足'}。`)
  lines.push('')

  const score = s.score_b
  const scoreLabel = score >= 80 ? '綠燈' : score >= 60 ? '黃燈' : '紅燈'
  const missing: string[] = []
  if (!s.is_squeeze) missing.push('沒有BB壓縮（is_squeeze=false）→ 少15分')
  if (s.vol_ratio > 0.5) missing.push(`量縮不夠（vol_ratio=${s.vol_ratio.toFixed(2)}，>0.5）→ 少10分`)
  if (s.margin_5d_chg > 0) missing.push(`融資近5日增加（+${(s.margin_5d_chg * 100).toFixed(1)}%）→ 扣分`)
  if (s.lending_5d_chg > 0) missing.push(`借券近5日增加（+${(s.lending_5d_chg * 100).toFixed(1)}%）→ 扣分`)

  if (missing.length > 0) {
    lines.push(`B分${score}（${scoreLabel}）低的原因：`)
    missing.forEach(m => lines.push(`  ${m}`))
  } else {
    lines.push(`B分${score}（${scoreLabel}）：各項條件均達標。`)
  }

  if (s.score_a > 0) {
    lines.push(`A分${s.score_a.toFixed(0)}（策略A突破品質）`)
  }
  lines.push('')

  if (s.dip_bonus > 0) {
    const isFull = s.dip_bonus >= 5
    lines.push(`+${s.dip_bonus}資${isFull ? '（滿分）才是這檔最關鍵的地方' : ''}：最近${s.dip_bonus}次股價下跌日，法人都逆勢買超。`)
    lines.push('')
  }

  if (s.holders_bonus !== null && s.holders_bonus !== undefined) {
    const absN = Math.abs(s.holders_bonus)
    const dir = s.holders_bonus > 0 ? `增加 ${absN.toFixed(2)}%` : s.holders_bonus < 0 ? `減少 ${absN.toFixed(2)}%` : `與上週相同`
    const comment = s.holders_bonus > 0 ? '大戶加碼，籌碼向上集中，偏多訊號。' : s.holders_bonus < 0 ? '大戶減倉，籌碼分散，需注意。' : '大戶持股穩定。'
    lines.push(`${s.holders_bonus > 0 ? '+' : ''}${s.holders_bonus.toFixed(2)}%戶：千張以上大戶本週比上週${dir}。${comment}`)
    lines.push('')
  }

  if (score >= 80) {
    lines.push(`結論：各項條件強勢，可列入優先觀察。`)
  } else if (s.dip_bonus >= 4 && score < 60) {
    lines.push(`結論：基礎面條件普通，但籌碼沉澱訊號很強。偏謹慎看待，等量縮或BB壓縮成形再考慮。`)
  } else if (s.dip_bonus >= 4) {
    lines.push(`結論：籌碼沉澱訊號強，基礎面也在水準線，可關注後續型態發展。`)
  } else {
    lines.push(`結論：訊號尚在醞釀，持續觀察法人籌碼方向。`)
  }

  return lines.join('\n')
}

function AppearanceBadge({ appearances, streak }: { appearances: number; streak: number }) {
  if (streak >= 2)
    return <span className="px-2 py-0.5 bg-purple-900 text-purple-300 text-xs rounded-full">連續 {streak} 日</span>
  if (appearances === 1)
    return <span className="px-2 py-0.5 bg-orange-900 text-orange-300 text-xs rounded-full">五日首次</span>
  return <span className="px-2 py-0.5 bg-gray-700 text-gray-300 text-xs rounded-full">5日 {appearances} 次</span>
}

interface StockCardProps { stock: ScreenerResult; onResearchStock?: (code: string) => void }

export function StockCard({ stock, onResearchStock }: StockCardProps) {
  const score = stock.score_b
  const scoreColor = score >= 80 ? 'text-green-400' : score >= 60 ? 'text-yellow-400' : 'text-red-400'
  const analysis = generateAnalysis(stock)
  const daysSinceCalc = Math.floor((Date.now() - new Date(stock.calc_date).getTime()) / 86400000)
  const dateColor = daysSinceCalc <= 3 ? 'text-green-400' : 'text-gray-600'

  return (
    <div className="relative group bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-blue-500 transition-colors">
      <div className="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity
        absolute z-50 left-full top-0 ml-3 w-[380px]
        text-[11px] leading-relaxed bg-gray-950 border border-blue-500
        text-gray-200 rounded-lg p-3 shadow-2xl pointer-events-auto whitespace-pre-wrap text-left select-text">
        {analysis}
        <div
          className="mt-2 pt-2 border-t border-blue-800 text-blue-400 text-[10px] cursor-pointer hover:text-blue-300 select-none"
          onClick={() => navigator.clipboard.writeText(analysis)}
        >
          點擊複製全文
        </div>
        <span className="absolute top-3 right-full border-4 border-transparent border-r-blue-500" />
      </div>

      <div className="flex justify-between items-start mb-3">
        <div>
          <span
            className="text-white font-bold text-lg cursor-pointer hover:text-blue-400"
            onClick={() => onResearchStock?.(stock.code)}
          >{stock.code}</span>
          <span className="text-gray-400 text-lg ml-2">{stock.name}</span>
          <span className={`text-[10px] ml-2 ${dateColor}`}>{stock.calc_date.slice(5)} 篩選</span>
          <button
            className="ml-2 text-gray-600 hover:text-blue-400 text-xs transition-colors"
            title="複製解讀"
            onClick={e => { e.stopPropagation(); navigator.clipboard.writeText(analysis) }}
          >⎘</button>
        </div>
        <div className="flex items-stretch gap-1.5">
          <div className="text-center">
            {stock.score_a > 0 && (
              <div className="text-xs text-blue-400 font-semibold">A:{stock.score_a.toFixed(0)}</div>
            )}
            <span className={`text-2xl font-black leading-none ${scoreColor}`}>{score}</span>
            <div className="text-[10px] text-gray-500">B分</div>
          </div>
          <div className="flex flex-col justify-end text-[10px] font-bold leading-none py-0.5 gap-[3px]">
            <span className={`${stock.dip_bonus !== 0 ? 'text-orange-400' : 'text-gray-600'}`}>
              {stock.dip_bonus > 0 ? '+' : ''}{stock.dip_bonus}資
            </span>
            {[
              { val: stock.holders_bonus, label: '1w' },
              { val: stock.holders_w2,    label: '2w' },
              { val: stock.holders_w3,    label: '3w' },
            ].map(({ val, label }) => val != null ? (
              <span key={label} className={`${val > 0 ? 'text-sky-400' : val < 0 ? 'text-pink-400' : 'text-gray-500'}`}>
                <span className="text-[8px] text-gray-600 font-normal mr-0.5">{label}</span>
                {val > 0 ? '+' : ''}{val.toFixed(2)}%
              </span>
            ) : null)}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {stock.tags.filter(t => ['A', 'B', 'A+B'].includes(t)).map(tag => (
          <span key={tag} className={`px-2 py-0.5 text-xs rounded-full font-semibold ${tag === 'B' ? 'bg-blue-900 text-blue-300' : 'bg-green-900 text-green-300'}`}>策略 {tag}</span>
        ))}
        {stock.is_squeeze && (() => {
          const hasB = stock.tags.some(t => t === 'B' || t === 'A+B')
          return hasB
            ? <span className="px-2 py-0.5 bg-teal-900 text-teal-300 text-xs rounded-full font-semibold">盤整⚡</span>
            : <span className="px-2 py-0.5 bg-gray-700 text-gray-300 text-xs rounded-full">盤整</span>
        })()}
        <AppearanceBadge appearances={stock.appearances_5d} streak={stock.streak} />
      </div>

      <BBGauge position={stock.bb_position} />

      <div className="text-xs text-gray-500 text-center mt-1 flex justify-center gap-3">
        <span>創高位階 {stock.bb_peak.toFixed(1)}</span>
        <span>|</span>
        <span>量比 {stock.vol_ratio.toFixed(2)}</span>
        {stock.change_pct !== 0 && (
          <>
            <span>|</span>
            <span className={stock.change_pct >= 0 ? 'text-green-500' : 'text-red-500'}>
              {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct.toFixed(2)}%
            </span>
          </>
        )}
      </div>

      <ChipBar stock={stock} />
      <PriceSparkline code={stock.code} />
    </div>
  )
}
