import { useState, useEffect } from 'react'
import axios from 'axios'
import type { ScreenerResult, DataStatus } from '../types'

export function useScreener() {
  const [results, setResults] = useState<ScreenerResult[]>([])
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      axios.get<ScreenerResult[]>('/api/screener'),
      axios.get<DataStatus>('/api/status'),
    ])
      .then(([res, statusRes]) => {
        setResults(res.data)
        setStatus(statusRes.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return { results, status, loading }
}
