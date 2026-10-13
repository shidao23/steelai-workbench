import { useEffect, useMemo, useState } from 'react'
import { artifactUrl, type Artifact, type RunRecord } from '../api/client'
import { DataTable, EmptyState, StatusBadge, formatBytes } from './ui'
import { LineChart, type Series } from './LineChart'

interface ArtifactView {
  columns: string[]
  rows: string[][]
}

function parseCsv(text: string): ArtifactView {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== '')
  if (lines.length === 0) return { columns: [], rows: [] }
  const header = lines[0].split(',')
  const rows = lines.slice(1, 201).map((line) => line.split(','))
  return { columns: header, rows }
}

function numericColumn(view: ArtifactView, index: number): number[] {
  return view.rows.map((row) => Number(row[index])).filter((value) => Number.isFinite(value))
}

export function RunDetail({ run }: { run: RunRecord }) {
  const [selected, setSelected] = useState<Artifact | null>(null)
  const [view, setView] = useState<ArtifactView | null>(null)
  const [text, setText] = useState('')
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    setSelected(null)
    setView(null)
    setText('')
    setLoadError('')
  }, [run.run_id])

  const textArtifacts = useMemo(
    () => run.artifacts.filter((item) => /\.(csv|json|md|txt|log)$/i.test(item.rel)),
    [run.artifacts],
  )
  const imageArtifacts = useMemo(
    () => run.artifacts.filter((item) => /\.(png|jpg|jpeg|bmp|tif|tiff)$/i.test(item.rel)),
    [run.artifacts],
  )

  async function openArtifact(artifact: Artifact) {
    setLoadError('')
    setSelected(artifact)
    setView(null)
    setText('')
    try {
      const response = await fetch(artifactUrl(run.run_id, artifact.rel))
      if (!response.ok) throw new Error(`${response.status}`)
      const body = await response.text()
      if (/\.csv$/i.test(artifact.rel)) setView(parseCsv(body))
      else setText(body.slice(0, 6000))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
    }
  }

  const chartSeries: Series[] = useMemo(() => {
    if (!view || view.columns.length < 2 || view.rows.length === 0) return []
    const xColumn = 0
    const series: Series[] = []
    for (let index = 1; index < view.columns.length && series.length < 4; index += 1) {
      const values = numericColumn(view, index)
      if (values.length !== view.rows.length) continue
      series.push({
        name: view.columns[index] || `列${index + 1}`,
        x: view.rows.map((row) => row[xColumn] ?? ''),
        y: values,
        unit: view.columns[index].match(/\(([^)]+)\)/)?.[1] ?? '',
        mode: 'lines+markers',
      })
    }
    return series
  }, [view])

  return (
    <div className="run-detail">
      <div className="run-summary">
        <div><code>{run.run_id}</code> <StatusBadge status={run.status} /></div>
        <div className="muted small">
          {run.tool_label} · 退出码 {run.exit_code ?? '—'} · 用时 {run.duration_sec ?? '—'}s · {run.created}
        </div>
        {run.error && <p className="warn-text">{run.error}</p>}
        {run.result_dirs.length > 0 && (
          <p className="muted small">结果目录：{run.result_dirs.map((item) => <code key={item}>{item}</code>)}</p>
        )}
      </div>

      <details className="run-params" open>
        <summary>运行参数</summary>
        <pre className="code-block small">{JSON.stringify(run.params, null, 2)}</pre>
      </details>

      {run.stdout_tail && (
        <details className="run-stdout">
          <summary>标准输出（尾部）</summary>
          <pre className="code-block small">{run.stdout_tail}</pre>
        </details>
      )}
      {run.stderr_tail && (
        <details className="run-stderr">
          <summary>标准错误（尾部）</summary>
          <pre className="code-block small">{run.stderr_tail}</pre>
        </details>
      )}

      <div className="artifact-block">
        <h4>产物（{run.artifacts.length}）</h4>
        {run.artifacts.length === 0 && <EmptyState title="没有产物" hint="该运行没有生成登记类型的文件。" />}
        {run.artifacts.length > 0 && (
          <ul className="artifact-list">
            {run.artifacts.map((artifact) => (
              <li key={artifact.rel}>
                <button type="button" className="linkish" onClick={() => void openArtifact(artifact)}>
                  {artifact.rel}
                </button>
                <span className="muted small">{formatBytes(artifact.size)}</span>
                <a className="chip" href={artifactUrl(run.run_id, artifact.rel)} download>下载</a>
              </li>
            ))}
          </ul>
        )}
      </div>

      {loadError && <p className="warn-text">读取产物失败：{loadError}</p>}

      {selected && (
        <div className="artifact-view">
          <h4>{selected.rel}</h4>
          {view && (
            <>
              <DataTable columns={view.columns} rows={view.rows} max={60} />
              {chartSeries.length > 0 && (
                <LineChart
                  title={`${run.tool_label} · ${selected.name}`}
                  xTitle={view.columns[0]}
                  yTitle={chartSeries.map((item) => item.unit || item.name).join(' / ')}
                  series={chartSeries}
                />
              )}
            </>
          )}
          {!view && text && <pre className="code-block">{text}</pre>}
        </div>
      )}

      {imageArtifacts.length > 0 && (
        <div className="artifact-view">
          <h4>图像产物</h4>
          <div className="image-row">
            {imageArtifacts.map((artifact) => (
              <figure key={artifact.rel}>
                <img src={artifactUrl(run.run_id, artifact.rel)} alt={artifact.rel} />
                <figcaption className="muted small">{artifact.rel}</figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}

      {textArtifacts.length === 0 && run.artifacts.length > 0 && (
        <p className="muted small">该运行的产物均为二进制/图像，可直接下载。</p>
      )}
    </div>
  )
}
