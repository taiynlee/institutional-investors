import type { ReactNode } from 'react'

interface TooltipProps {
  text: string
  children: ReactNode
  width?: string
}

export function Tooltip({ text, children, width = 'w-52' }: TooltipProps) {
  return (
    <span className="relative group cursor-help">
      {children}
      <span className={`invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity
        absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5
        ${width} text-[11px] leading-snug bg-gray-800 border border-gray-600
        text-gray-200 rounded-lg p-2 shadow-xl whitespace-normal text-center pointer-events-none`}>
        {text}
        <span className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-600" />
      </span>
    </span>
  )
}
