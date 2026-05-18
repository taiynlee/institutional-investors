import { useState, useEffect } from 'react'
import axios from 'axios'
import { useScreener } from '../hooks/useScreener'
import { StockCard } from '../components/StockCard'
import { TagFilter } from '../components/TagFilter'

export function Dashboard() {
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [allTags, setAllTags] = useState<string[]>([])
  const { results, status, loading } = useScreener(selectedTags)

  useEffect(() => {
    axios.get<{ tags: string[] }>('/api/tags').then(r => setAllTags(r.data.tags)).catch(() => {})
  }, [])

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">台股電子股主力篩選</h1>
            <p className="text-gray-400 text-sm">創高後拉回、主力未出場</p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${status?.is_reliable ? 'text-green-400' : 'text-yellow-400'}`}>
              {status?.is_reliable ? '資料完整' : '資料更新中'}
            </div>
            <div className="text-xs text-gray-500">{status?.date} 21:00 後可信</div>
          </div>
        </div>

        {status && (
          <div className="flex gap-4 mb-6 p-3 bg-gray-900 rounded-lg flex-wrap items-center">
            {status.jobs.length === 0 && (
              <span className="text-xs text-gray-500">今日尚未執行更新排程</span>
            )}
            {status.jobs.map(job => {
              const labels: Record<string, string> = {
                job1: '法人+價量', job2: '融資融券', job3: '持股集中', job4: '篩選完成'
              }
              return (
                <div key={job.name} className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${job.status === 'success' ? 'bg-green-400' : 'bg-red-500'}`} />
                  <span className="text-xs text-gray-400">
                    {labels[job.name] ?? job.name}
                    {job.rows > 0 && <span className="text-gray-600 ml-1">({job.rows})</span>}
                  </span>
                </div>
              )
            })}
            <span className="text-xs text-gray-500 ml-auto">篩出 {results.length} 檔</span>
          </div>
        )}

        <TagFilter allTags={allTags} selected={selectedTags} onChange={setSelectedTags} />

        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無符合條件的股票</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(stock => <StockCard key={stock.code} stock={stock} />)}
          </div>
        )}
      </div>
    </div>
  )
}
