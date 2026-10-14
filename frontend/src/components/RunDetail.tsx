import { useEffect, useMemo, useState } from 'react'
import { artifactBlobUrl, artifactText, type Artifact, type RunRecord } from '../api/client'
import { DataTable, EmptyState, StatusBadge, formatBytes } from './ui'
import { LineChart, type Series } from './LineChart'

interface ArtifactView {
  columns: string[]
  rows: string[][]
}

/**
 * 与后端 `tabular.read_table` 同一套解释的 CSV 解析：支持引号、引号内逗号/换行、
 * 双引号转义、空字段；不要再用 `line.split(',')`（那会把 `S1,"a, b",12` 拆成 4 列）。
 */
function parseCsv(text: string): ArtifactView {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
        }
      } else {
        field += char
      }
      continue
    }
    if (char === '"') {
      quoted = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else if (char !== '\r') {
      field += char
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  if (rows.length === 0) return { columns: [], rows: [] }
  const [columns, ...body] = rows
  return { columns, rows: body.slice(0, 201) }
}

function numericColumn(view: ArtifactView, index: number): number[] {
  return view.rows.map((row) => Number(row[index])).filter((value) => Number.isFinite(value))
}

export function RunDetail({ run }: { run: RunRecord }) {
  const [selected, setSelected] = useState<Artifact | null>(null)
  const [view, setView] = useState<ArtifactView | null>(null)
  const [text, setText] = useState('')
  const [loadError, setLoadError] = useState('')
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    setSelected(null)
    setView(null)
    setText('')
    setLoadError('')
    setImageUrls({})
  }, [run.run_id])

  const textArtifacts = useMemo(
    () => run.artifacts.filter((item) => /\.(csv|json|md|txt|log)$/i.test(item.rel)),
    [run.artifacts],
  )
  const imageArtifacts = useMemo(
    () => run.artifacts.filter((item) => /\.(png|jpg|jpeg|bmp|tif|tiff)$/i.test(item.rel)),
    [run.artifacts],
  )

  // 图像/二进制用带令牌的 blob URL（不放 token 进 URL）
  useEffect(() => {
    let alive = true
    const missing = imageArtifacts.filter((item) => !imageUrls[item.rel])
    if (missing.length === 0) return
    void Promise.all(
      missing.map(async (item) => {
        try {
          return [item.rel, await artifactBlobUrl(run.run_id, item.rel)] as const
        } catch {
          return null
        }
      }),
    ).then((entries) => {
      if (!alive) return
      const next: Record<string, string> = {}
      for (const entry of entries) if (entry) next[entry[0]] = entry[1]
      if (Object.keys(next).length > 0) setImageUrls((previous) => ({ ...previous, ...next }))
    })
    return () => {
      alive = false
    }
  }, [imageArtifacts, imageUrls, run.run_id])

  async function openArtifact(artifact: Artifact) {
    setLoadError('')
    setSelected(artifact)
    setView(null)
    setText('')
    try {
      const body = await artifactText(run.run_id, artifact.rel)
      if (/\.csv$/i.test(artifact.rel)) setView(parseCsv(body))
      else setText(body.slice(0, 6000))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error))
    }
  }

  async function download(artifact: Artifact) {
    setLoadError('')
    try {
      const url = await artifactBlobUrl(run.run_id, artifact.rel)
      const link = document.createElement('a')
      link.href = url
      link.download = artifact.name
      document.body.appendChild(link)
      link.click()
      link.remove()
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
        {(run.actor_kind || run.session_id) && (
          <div className="muted small">
            归属：<code>{run.actor_kind || run.actor}</code>
            {run.session_id ? ` · 会话 ${run.session_id.slice(0, 8)}…` : ''}
            {run.approval_origin
              ? ` · 确认来源 ${run.approval_origin}（${run.approval_reviewer || '未署名'}）`
              : ''}
            {run.approval_revision ? ` · 映射修订 ${run.approval_revision}` : ''}
            {run.approval_synthetic ? ' · 合成验收' : ''}
          </div>
        )}
        {run.actual_input_sha256 && (
          <div className="muted small">
            本次实际输入：<code>{run.actual_input_file}</code>{' '}
            <code className="hash">{run.actual_input_sha256.slice(0, 12)}…</code>
            {run.approval_input_sha256
              ? ` · 审批覆盖 ${run.approval_input_file || '—'} ` +
                `${run.approval_input_sha256.slice(0, 12)}…`
              : ''}
          </div>
        )}
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
                <button type="button" className="chip" onClick={() => void download(artifact)}>下载</button>
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
                {imageUrls[artifact.rel]
                  ? <img src={imageUrls[artifact.rel]} alt={artifact.rel} />
                  : <span className="muted small">载入中…</span>}
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
