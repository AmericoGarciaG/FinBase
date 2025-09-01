export type Interval = '1min' | '1hour' | '1day'

const API_BASE = '/api'

export async function getSymbols(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/v1/symbols`)
  if (!res.ok) throw new Error('Failed to load symbols')
  const json = await res.json()
  return (json.symbols ?? []) as string[]
}

export interface Candle {
  time: number // seconds since epoch (UTC)
  open?: number
  high?: number
  low?: number
  close?: number
  volume?: number
}

export async function getHistory(
  ticker: string,
  interval: Interval,
  limit = 500,
  opts?: { startDate?: string; endDate?: string }
): Promise<Candle[]> {
  const params = new URLSearchParams({ interval, limit: String(limit) })
  if (opts?.startDate) params.set('start_date', opts.startDate)
  if (opts?.endDate) params.set('end_date', opts.endDate)
  const res = await fetch(`${API_BASE}/v1/data/history/${encodeURIComponent(ticker)}?${params.toString()}`)
  if (!res.ok) throw new Error('Failed to load history')
  const json = await res.json()
  const data = (json.data ?? []) as Array<{ timestamp: string; open?: number; high?: number; low?: number; close?: number; volume?: number }>
  return data.map(d => ({
    time: Math.floor(new Date(d.timestamp).getTime() / 1000),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    volume: d.volume,
  }))
}

