import { useEffect, useRef, useState } from 'react'
import axios from 'axios'

// Global server-time offset (ms). Initialized once, shared across consumers.
let _offsetMs = 0
let _synced = false
const _listeners: Array<(offset: number) => void> = []

async function syncServerTime() {
  if (_synced) return
  try {
    const t0 = Date.now()
    const r = await axios.get<{ timestamp_ms: number }>('/api/server-time')
    const t1 = Date.now()
    _offsetMs = r.data.timestamp_ms - Math.round((t0 + t1) / 2)
    _synced = true
    _listeners.forEach(fn => fn(_offsetMs))
  } catch {
    // Fall back to local clock
    _synced = true
  }
}

/** Returns current server-synced Taiwan time as a Date */
export function serverNow(): Date {
  return new Date(Date.now() + _offsetMs)
}

/** ms until next occurrence of HH:MM (Taiwan time) */
export function msUntilNextTaiwanTime(hour: number, minute: number): number {
  const now = serverNow()
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Taipei',
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now).map(p => [p.type, p.value])
  )
  const target = new Date(
    `${parts.year}-${parts.month}-${parts.day}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00+08:00`
  )
  if (target <= now) target.setDate(target.getDate() + 1)
  return target.getTime() - now.getTime()
}

/** Hook: ensures server time is synced, returns offset (ms) */
export function useServerTimeSync(): number {
  const [offset, setOffset] = useState(_offsetMs)
  useEffect(() => {
    if (!_synced) {
      _listeners.push(setOffset)
      syncServerTime()
      return () => {
        const i = _listeners.indexOf(setOffset)
        if (i >= 0) _listeners.splice(i, 1)
      }
    }
  }, [])
  return offset
}

/** Hook: ticking display clock (Taiwan time), synced to server */
export function useServerClock(): { date: string; time: string } | null {
  const [display, setDisplay] = useState<{ date: string; time: string } | null>(null)
  const offsetRef = useRef(_offsetMs)

  useEffect(() => {
    if (!_synced) {
      const handler = (off: number) => { offsetRef.current = off }
      _listeners.push(handler)
      syncServerTime()
      return () => {
        const i = _listeners.indexOf(handler)
        if (i >= 0) _listeners.splice(i, 1)
      }
    }
  }, [])

  useEffect(() => {
    const tick = () => {
      const now = new Date(Date.now() + offsetRef.current)
      const fmt = new Intl.DateTimeFormat('zh-TW', {
        timeZone: 'Asia/Taipei',
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
      })
      const parts = Object.fromEntries(fmt.formatToParts(now).map(p => [p.type, p.value]))
      setDisplay({ date: `${parts.month}/${parts.day}`, time: `${parts.hour}:${parts.minute}:${parts.second}` })
    }
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [])

  return display
}
