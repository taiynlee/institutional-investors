import { useState, useEffect } from 'react'
import axios from 'axios'
import type { ScreenerResult, DataStatus } from '../types'

export function useScreener(tags: string[]) {
  const [results, setResults] = useState<ScreenerResult[]>([])
  const [status, setStatus] = useState<DataStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const tagParam = tags.length > 0 ? `?tags=${tags.join(',')}` : ''
    setLoading(true)
    Promise.all([
      axios.get<ScreenerResult[]>(`/api/screener${tagParam}`),
      axios.get<DataStatus>('/api/status'),
    ])
      .then(([res, statusRes]) => {
        setResults(res.data)
        setStatus(statusRes.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tags.join(',')])

  return { results, status, loading }
}
