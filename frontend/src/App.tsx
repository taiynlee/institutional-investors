import { useState } from 'react'
import { Dashboard } from './pages/Dashboard'
import { Result } from './pages/Result'
import { Holders } from './pages/Holders'
import './index.css'

type Tab = 'screener' | 'result' | 'holders'

export default function App() {
  const [tab, setTab] = useState<Tab>('screener')

  return (
    <div>
      <div className="bg-gray-900 border-b border-gray-800 px-6 py-2 flex gap-4">
        <button
          onClick={() => setTab('screener')}
          className={`text-sm font-medium px-3 py-1 rounded ${tab === 'screener' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
        >
          篩選結果
        </button>
        <button
          onClick={() => setTab('result')}
          className={`text-sm font-medium px-3 py-1 rounded ${tab === 'result' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
        >
          篩選績效
        </button>
        <button
          onClick={() => setTab('holders')}
          className={`text-sm font-medium px-3 py-1 rounded ${tab === 'holders' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-white'}`}
        >
          千張大戶
        </button>
      </div>
      {tab === 'screener' ? <Dashboard /> : tab === 'result' ? <Result /> : <Holders />}
    </div>
  )
}
