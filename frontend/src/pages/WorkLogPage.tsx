import { useEffect, useState } from 'react'
import { useSession } from '../state/session'
import { EmptyState, StatusBadge, formatBytes } from '../components/ui'
import { RunDetail } from '../components/RunDetail'

export function WorkLogPage() {
  const session = useSession()
  const [draft, setDraft] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState('')

  useEffect(() => {
    setDraft(session.context?.handoff_markdown ?? '')
    setSelected('')
  }, [session.context?.handoff_markdown, session.taskId])

  const active = session.runs.find((run) => run.run_id === selected)
    ?? session.runs.find((run) => run.run_id === session.activeRunId)
    ?? session.runs[0]
    ?? null

  async function save() {
    setMessage('')
    try {
      await session.saveHandoff(draft)
      setMessage('已写入 handoff.md（同一 task_id，换 AI 可直接接续）。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>工作记录</h2>
        <p className="muted">
          同一 <code>project_id / task_id / run_id</code>：软件只记生产者，参数、执行状态、来源与限制都留在这里。
        </p>
      </div>

      <section className="panel">
        <h3>任务说明</h3>
        {!session.context && <EmptyState title="未选择任务" hint="在“项目”页选择或新建一个任务。" />}
        {session.context && (
          <>
            <pre className="code-block small">{session.context.task_markdown}</pre>
            <p className="muted small">任务根：<code>{session.context.root}</code></p>
          </>
        )}
      </section>

      <section className="panel">
        <h3>运行记录（{session.runs.length}）</h3>
        {session.runs.length === 0 && (
          <EmptyState title="还没有运行" hint="运行任何工具后，这里会列出参数、退出码与产物。" />
        )}
        {session.runs.length > 0 && (
          <table className="data-table">
            <thead>
              <tr><th>run_id</th><th>工具</th><th>状态</th><th>退出码</th><th>用时</th><th>产物</th><th></th></tr>
            </thead>
            <tbody>
              {session.runs.map((run) => (
                <tr key={run.run_id}>
                  <td><code>{run.run_id}</code></td>
                  <td>{run.tool_label}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.exit_code ?? '—'}</td>
                  <td>{run.duration_sec ?? '—'}s</td>
                  <td>{run.artifacts.length}</td>
                  <td>
                    <button type="button" className="chip" onClick={() => setSelected(run.run_id)}>详情</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {active && (
        <section className="panel">
          <h3>运行详情 · <code>{active.run_id}</code></h3>
          <RunDetail run={active} />
        </section>
      )}

      <section className="panel">
        <h3>接手摘要（handoff.md）</h3>
        <p className="muted small">
          另一个 AI 读同一 README、同一任务目录与这份摘要即可接续；摘要与任务一起落盘，不依赖聊天记录。
        </p>
        <textarea rows={10} value={draft} onChange={(event) => setDraft(event.target.value)}
                  placeholder="记录：本任务做了什么、输入依据、产物相对路径与版本、未决项与下一步。" />
        <button type="button" className="primary" onClick={() => void save()} disabled={session.busy !== ''}>
          保存接手摘要
        </button>
        {message && <p className="cap-message">{message}</p>}
      </section>

      <section className="panel">
        <h3>本任务产物索引</h3>
        {session.artifacts.length === 0
          ? <EmptyState title="无产物" hint="运行后会列出。" />
          : (
            <ul className="artifact-list">
              {session.artifacts.map((artifact) => (
                <li key={`${artifact.run_id}-${artifact.rel}`}>
                  <code>{artifact.rel}</code>
                  <span className="muted small">{artifact.run_id} · {formatBytes(artifact.size)}</span>
                </li>
              ))}
            </ul>
          )}
      </section>
    </div>
  )
}
