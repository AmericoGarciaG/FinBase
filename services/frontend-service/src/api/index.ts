/**
 * Supported aggregation intervals returned by the API.
 */
export type Interval = '1min' | '1hour' | '1day'

import type { UTCTimestamp, CandlestickData } from 'lightweight-charts'

const API_BASE = '/api'

/**
 * Fetch the list of available symbols from the API.
 *
 * Returns a sorted array of distinct tickers.
 */
export async function getSymbols(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/v1/symbols`)
  if (!res.ok) throw new Error('Failed to load symbols')
  const json = await res.json()
  return (json.symbols ?? []) as string[]
}

/**
 * Normalized candle format used by the frontend charting components.
 * time is seconds since epoch (UTC).
 */
export type Candle = CandlestickData<UTCTimestamp>

/**
 * Fetch normalized OHLCV candles for a ticker.
 *
 * Params:
 * - ticker: Symbol, e.g. 'AAPL'.
 * - interval: Aggregation interval.
 * - limit: Max candles to return (server-enforced bounds apply).
 * - opts.startDate/endDate: Optional ISO dates to bound the range.
 */
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
    time: Math.floor(new Date(d.timestamp).getTime() / 1000) as UTCTimestamp,
    open: Number(d.open ?? NaN),
    high: Number(d.high ?? NaN),
    low: Number(d.low ?? NaN),
    close: Number(d.close ?? NaN),
  }))
}

