import { useEffect, useRef, useState } from 'react'
import { useSession } from '../state/session'
import { EmptyState, StatusBadge, formatBytes } from '../components/ui'
import { RunDetail } from '../components/RunDetail'

/**
 * WO-32 §2 — 草稿按 `project/task` 分桶，并落到 sessionStorage。
 *
 * 切换任务后不会把上一份草稿保存到新任务上：草稿存在各自的桶里，回到某任务时
 * 原样恢复；保存前再校验一次当前作用域，迟到的保存一律拒绝。
 *
 * 桶键只用 `project/task`（不带 epoch）：epoch 每次切换都会变，用它当键会让
 * "回到同一任务"也变成新桶、草稿丢失。放在 sessionStorage 里则保证离开本页
 * （组件卸载）或刷新后草稿仍在，且不会跨任务串。
 */
const DRAFTS_KEY = 'steelai.worklog.drafts.v1'

function readDrafts(): Map<string, string> {
  try {
    const raw = window.sessionStorage.getItem(DRAFTS_KEY)
    if (!raw) return new Map()
    const parsed = JSON.parse(raw) as Record<string, string>
    return new Map(Object.entries(parsed))
  } catch {
    return new Map()
  }
}

function persistDrafts(drafts: Map<string, string>): void {
  try {
    window.sessionStorage.setItem(DRAFTS_KEY, JSON.stringify(Object.fromEntries(drafts)))
  } catch {
    /* 无痕模式等场景下不可用：退化为仅本页内存草稿，不阻塞使用 */
  }
}

export function WorkLogPage() {
  const session = useSession()
  const [draft, setDraft] = useState('')
  const [message, setMessage] = useState('')
  const [selected, setSelected] = useState('')
  const drafts = useRef<Map<string, string>>(readDrafts())
  const scopeKey = session.selection
    ? `${session.selection.projectId}/${session.selection.taskId}`
    : ''
  const seededScope = useRef('')
  const seededHandoff = useRef('')

  // 换任务时立刻从草稿桶取（没有就是空），不等 context 到达：
  // 否则 context 在路上时会把输入框清空一下，看起来像"草稿丢了"。
  useEffect(() => {
    if (!scopeKey) {
      setDraft('')
      seededScope.current = ''
      seededHandoff.current = ''
      return
    }
    if (seededScope.current === scopeKey) return
    seededScope.current = scopeKey
    seededHandoff.current = ''
    setSelected('')
    setDraft(drafts.current.get(scopeKey) ?? '')
  }, [scopeKey])

  // context 到了以后：只有本任务还没有草稿时，才用磁盘上的 handoff.md 垫底。
  useEffect(() => {
    if (!scopeKey || !session.context) return
    if (seededHandoff.current === scopeKey) return
    seededHandoff.current = scopeKey
    if (drafts.current.has(scopeKey)) return
    setDraft(session.context.handoff_markdown)
  }, [session.context, scopeKey])

  function edit(next: string) {
    setDraft(next)
    if (scopeKey) {
      drafts.current.set(scopeKey, next)
      persistDrafts(drafts.current)
    }
  }

  async function save() {
    setMessage('')
    try {
      await session.saveHandoff(draft)
      setMessage('已写入 handoff.md（同一 project/task，换 AI 可直接接续）。')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  const active = session.runs.find((run) => run.run_id === selected)
    ?? session.runs.find((run) => run.run_id === session.activeRunId)
    ?? session.runs[0]
    ?? null

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
          {scopeKey && <span className="muted"> 草稿按 <code>{scopeKey}</code> 分桶，切换任务不会串写。</span>}
        </p>
        <textarea rows={10} value={draft} onChange={(event) => edit(event.target.value)}
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
