import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi } from 'lightweight-charts'
import type { Candle, Interval } from '../api'
import { getHistory } from '../api'

interface Props {
  ticker: string
  interval: Interval
}

export const ChartComponent: React.FC<Props> = ({ ticker, interval }) => {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const dataRef = useRef<Candle[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  // Create chart
  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#111827' },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
      timeScale: { rightOffset: 12, barSpacing: 8, fixLeftEdge: false },
      rightPriceScale: { borderVisible: false },
      grid: { horzLines: { color: '#eee' }, vertLines: { color: '#f6f6f6' } },
      crosshair: { mode: 0 },
    })
    const series = chart.addCandlestickSeries({ priceLineVisible: false })
    chartRef.current = chart
    seriesRef.current = series

    const onResize = () => {
      if (!containerRef.current || !chartRef.current) return
      chartRef.current.applyOptions({
        width: containerRef.current.clientWidth,
        height: containerRef.current.clientHeight,
      })
    }
    window.addEventListener('resize', onResize)

    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // Load initial data & when ticker/interval change
  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!seriesRef.current) return
      const candles = await getHistory(ticker, interval, 500)
      if (cancelled) return
      dataRef.current = candles
      seriesRef.current.setData(candles)
      chartRef.current?.timeScale().fitContent()
    }
    load().catch(console.error)
    return () => { cancelled = true }
  }, [ticker, interval])

  // Infinite scroll to load older data
  useEffect(() => {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series) return

    const handler = async () => {
      if (loadingMore) return
      const data = dataRef.current
      if (!data.length) return
      const earliest = data[0]
      const logical = chart.timeScale().getVisibleLogicalRange()
      if (!logical) return
      const left = logical.from
      // If user scrolls/pans sufficiently left (near the first bar), fetch more
      if (left <= 5) {
        setLoadingMore(true)
        try {
          const endDateISO = new Date((earliest.time - 1) * 1000).toISOString()
          const more = await getHistory(ticker, interval, 500, { endDate: endDateISO })
          if (more.length) {
            // Prepend maintaining ascending order
            dataRef.current = [...more, ...dataRef.current]
            series.setData(dataRef.current)
          }
        } catch (e) {
          // ignore
        } finally {
          setLoadingMore(false)
        }
      }
    }

    const sub = () => handler()
    chart.timeScale().subscribeVisibleLogicalRangeChange(sub)
    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(sub)
    }
  }, [ticker, interval, loadingMore])

  // WebSocket live updates
  useEffect(() => {
    const loc = window.location
    const wsScheme = loc.protocol === 'https:' ? 'wss' : 'ws'
    const wsUrl = `${wsScheme}://${loc.host}/api/v1/stream`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({ action: 'subscribe', tickers: [ticker], interval }))
    })
    ws.addEventListener('message', (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg?.type === 'candle' && msg.ticker === ticker && msg.interval === interval) {
          const d = msg.data
          if (!seriesRef.current) return
          const update = {
            time: Math.floor(new Date(d.timestamp).getTime() / 1000),
            open: d.open, high: d.high, low: d.low, close: d.close,
          }
          seriesRef.current.update(update)
          // also update our buffer
          const last = dataRef.current[dataRef.current.length - 1]
          if (last && last.time === update.time) {
            dataRef.current[dataRef.current.length - 1] = { ...last, ...update }
          } else {
            dataRef.current.push(update)
          }
        }
      } catch (_) {}
    })
    return () => {
      try { ws.close() } catch (_) {}
      wsRef.current = null
    }
  }, [ticker, interval])

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
}

