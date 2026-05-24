interface BBGaugeProps {
  position: number
}

export function BBGauge({ position }: BBGaugeProps) {
  const clamped = Math.max(-10, Math.min(10, position))
  const pct = ((clamped + 10) / 20) * 100
  const color =
    position > 5 ? '#22c55e' :
    position > 0 ? '#3b82f6' :
    position > -3 ? '#f97316' : '#ef4444'

  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>-10</span><span>0</span><span>+10</span>
      </div>
      <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px bg-gray-400" />
      </div>
      <div className="text-center text-sm font-bold mt-1" style={{ color }}>
        {position.toFixed(1)}
      </div>
    </div>
  )
}
