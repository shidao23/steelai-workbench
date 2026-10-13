/**
 * 曲线组件。改编思路来自 OpenBB Workspace `terminalpro/src/components/Charting/PlotlyChart.tsx`
 * （懒加载、按容器尺寸自适应、主题/config 与图对象分离），但**不照搬**其全局依赖：
 * 这里直接使用 `plotly.js-dist-min`（MIT）并按需懒加载。
 *
 * WO-31 §2 要求：不修改输入图对象、不抹掉科研标题/单位、空数据给出真实状态。
 * 因此 x/y 轴标题必须由调用方显式给出（含单位），空数据渲染“无数据”而不是空图。
 */

import { useEffect, useRef, useState } from 'react'

export interface Series {
  name: string
  x: (number | string)[]
  y: number[]
  unit?: string
  mode?: 'lines' | 'markers' | 'lines+markers'
}

interface Props {
  title: string
  xTitle: string
  yTitle: string
  series: Series[]
  height?: number
}

type PlotlyModule = { newPlot: (el: HTMLElement, data: unknown[], layout: unknown, config: unknown) => Promise<unknown>; purge: (el: HTMLElement) => void }

let plotlyPromise: Promise<PlotlyModule> | null = null

function loadPlotly(): Promise<PlotlyModule> {
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist-min').then((mod) => {
      const candidate = mod as unknown as { default?: PlotlyModule }
      return candidate.default ?? (mod as unknown as PlotlyModule)
    })
  }
  return plotlyPromise
}

export function LineChart({ title, xTitle, yTitle, series, height = 320 }: Props) {
  const container = useRef<HTMLDivElement | null>(null)
  const [failed, setFailed] = useState('')
  const hasData = series.some((item) => item.y.length > 0)

  useEffect(() => {
    if (!hasData || !container.current) return
    let cancelled = false
    loadPlotly()
      .then((Plotly) => {
        if (cancelled || !container.current) return
        const traces = series.map((item) => ({
          x: item.x,
          y: item.y,
          type: 'scatter',
          mode: item.mode ?? 'lines+markers',
          name: item.unit ? `${item.name} (${item.unit})` : item.name,
        }))
        const layout = {
          title: { text: title, font: { size: 14 } },
          margin: { l: 64, r: 16, t: 40, b: 48 },
          xaxis: { title: { text: xTitle }, zeroline: false },
          yaxis: { title: { text: yTitle }, zeroline: false },
          legend: { orientation: 'h', y: -0.22 },
          paper_bgcolor: 'rgba(0,0,0,0)',
          plot_bgcolor: 'rgba(0,0,0,0)',
          font: { family: 'Segoe UI, Microsoft YaHei, sans-serif', size: 12, color: '#21333E' },
        }
        return Plotly.newPlot(container.current, traces, layout, {
          displaylogo: false,
          responsive: true,
          modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
        })
      })
      .catch((error: unknown) => {
        if (!cancelled) setFailed(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [title, xTitle, yTitle, series, hasData])

  if (!hasData) {
    return (
      <div className="chart-empty" style={{ height }}>
        <strong>无数据可画</strong>
        <span className="muted">该运行没有产出可绘制的数值列；请先运行一次数据处理或统计。</span>
      </div>
    )
  }

  if (failed) {
    return (
      <div className="chart-empty" style={{ height }}>
        <strong>图表组件加载失败</strong>
        <span className="muted">{failed}</span>
      </div>
    )
  }

  return <div ref={container} className="chart-host" style={{ height }} />
}
