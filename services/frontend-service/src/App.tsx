import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ChartComponent } from './components/ChartComponent'
import { getSymbols } from './api'

const intervals = [
  { key: '1min', label: '1m' },
  { key: '1hour', label: '1H' },
  { key: '1day', label: '1D' },
] as const

export default function App() {
  const [symbols, setSymbols] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [ticker, setTicker] = useState<string>('AAPL')
  const [interval, setInterval] = useState<'1min' | '1hour' | '1day'>('1min')

  useEffect(() => {
    getSymbols().then(setSymbols).catch(() => setSymbols([]))
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase()
    if (!q) return symbols
    return symbols.filter(s => s.includes(q))
  }, [query, symbols])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'Inter, system-ui, Arial' }}>
      <header style={{ padding: '12px 16px', borderBottom: '1px solid #e5e7eb', display: 'flex', gap: 12, alignItems: 'center' }}>
        <strong>FinBase</strong>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            placeholder="Buscar símbolo (AAPL, MSFT, ... )"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ padding: '8px', border: '1px solid #cbd5e1', borderRadius: 6, minWidth: 260 }}
            list="symbols"
          />
          <datalist id="symbols">
            {filtered.slice(0, 50).map(s => (
              <option value={s} key={s} />
            ))}
          </datalist>
          <button onClick={() => setTicker(query.trim().toUpperCase() || ticker)} style={{ padding: '8px 12px' }}>Cargar</button>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {intervals.map(i => (
            <button
              key={i.key}
              onClick={() => setInterval(i.key)}
              style={{
                padding: '6px 10px',
                borderRadius: 6,
                border: '1px solid #cbd5e1',
                background: interval === i.key ? '#111827' : 'white',
                color: interval === i.key ? 'white' : '#111827',
                cursor: 'pointer'
              }}
            >{i.label}</button>
          ))}
        </div>
      </header>
      <main style={{ flex: 1, minHeight: 0 }}>
        <ChartComponent ticker={ticker} interval={interval} />
      </main>
    </div>
  )
}

