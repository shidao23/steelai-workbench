import { useMemo, useState } from 'react'
import { artifactUrl } from '../api/client'
import { useSession } from '../state/session'
import { EmptyState, StatusBadge, formatBytes } from '../components/ui'
import { GridLayout } from '../layout/GridLayout'
import { RunDetail } from '../components/RunDetail'

export function ArtifactsPage() {
  const session = useSession()
  const [reviewer, setReviewer] = useState('')
  const [message, setMessage] = useState('')

  const succeededRuns = useMemo(
    () => session.runs.filter((run) => run.status === 'succeeded'),
    [session.runs],
  )
  const active = session.runs.find((run) => run.run_id === session.activeRunId) ?? succeededRuns[0] ?? null

  async function promote(runId: string) {
    setMessage('')
    if (!reviewer.trim()) {
      setMessage('晋升需要具名人工审批人（不能用 system/agent/web）。')
      return
    }
    try {
      const response = await fetch(
        `/api/projects/${session.projectId}/tasks/${session.taskId}/promote`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ run_id: runId, reviewer: reviewer.trim() }),
        },
      )
      const body = await response.json()
      setMessage(response.status === 501
        ? `未接通（${body.status}）：${body.detail}`
        : JSON.stringify(body))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>成果</h2>
        <p className="muted">
          候选成果保留在任务 <code>runs/&lt;run_id&gt;/</code> 下，<b>不自动 accepted</b>、不覆盖 CURRENT。
          正式晋升要接上原 owner 的人审流程；未接通时这里会如实返回未接通，而不是假装成功。
        </p>
      </div>

      <section className="panel">
        <h3>任务产物清单（{session.artifacts.length}）</h3>
        {session.artifacts.length === 0 && (
          <EmptyState title="还没有产物" hint="先在“数据处理”或“分析工具”页运行一次工具。" />
        )}
        {session.artifacts.length > 0 && (
          <table className="data-table">
            <thead>
              <tr><th>产物</th><th>来源运行</th><th>工具</th><th>大小</th><th>SHA-256</th><th>下载</th></tr>
            </thead>
            <tbody>
              {session.artifacts.map((artifact) => (
                <tr key={`${artifact.run_id}-${artifact.rel}`}>
                  <td><code>{artifact.rel}</code></td>
                  <td><code>{artifact.run_id}</code></td>
                  <td>{artifact.tool_label}</td>
                  <td>{formatBytes(artifact.size)}</td>
                  <td><code className="hash">{artifact.sha256?.slice(0, 16)}…</code></td>
                  <td>
                    <a className="chip" href={artifactUrl(artifact.run_id ?? '', artifact.rel)} download>下载</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3>候选晋升（需要具名人工审批）</h3>
        <div className="form-row">
          <label className="field">
            <span className="field-label">审批人（真实姓名）</span>
            <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="例如 张工" />
          </label>
          <label className="field">
            <span className="field-label">候选运行</span>
            <select value={active?.run_id ?? ''} onChange={(event) => session.setActiveRun(event.target.value)}>
              {succeededRuns.length === 0 && <option value="">（没有成功运行）</option>}
              {succeededRuns.map((run) => (
                <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.tool_label}</option>
              ))}
            </select>
          </label>
        </div>
        <button type="button" className="primary" disabled={!active}
                onClick={() => active && void promote(active.run_id)}>
          提交晋升
        </button>
        {message && <p className="cap-message">{message}</p>}
      </section>

      <GridLayout
        projectId={session.projectId}
        page={`${session.page}_detail`}
        primaryLabel="产物明细"
        secondaryLabel="运行回放"
        primary={
          session.artifacts.length === 0
            ? <EmptyState title="无产物" hint="运行工具后产物会列出。" />
            : (
              <ul className="artifact-list">
                {session.artifacts.map((artifact) => (
                  <li key={`${artifact.run_id}-${artifact.rel}-detail`}>
                    <code>{artifact.rel}</code>
                    <span className="muted small">{artifact.tool_label}</span>
                    <StatusBadge status={artifact.status ?? 'succeeded'} />
                    <a className="chip" href={artifactUrl(artifact.run_id ?? '', artifact.rel)} download>下载</a>
                  </li>
                ))}
              </ul>
            )
        }
        secondary={active
          ? <RunDetail run={active} />
          : <EmptyState title="没有可回放的运行" hint="运行成功后可在右侧查看产物与曲线。" />}
      />
    </div>
  )
}
