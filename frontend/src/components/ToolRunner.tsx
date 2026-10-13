import { useEffect, useMemo, useState } from 'react'
import type { Capability, CapabilityField } from '../api/client'
import { useSession, type Scope } from '../state/session'
import { StatusBadge } from './ui'

function initialValue(field: CapabilityField): string {
  if (field.default !== null && field.default !== undefined) return String(field.default)
  if (field.kind === 'select' && field.options.length > 0) return field.options[0]
  return ''
}

/** 一个能力卡：按固定 schema 渲染参数、运行、显示真实状态。 */
export function ToolRunner({ capability }: { capability: Capability }) {
  const session = useSession()
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {}
    for (const field of capability.fields) seed[field.name] = initialValue(field)
    return seed
  })
  const [message, setMessage] = useState('')
  // 打开这张卡时的作用域快照：文件下拉/提交都以它为准，切换后下拉框与提交目标都不串
  const [scope, setScope] = useState<Scope | null>(() => session.beginScope())

  useEffect(() => {
    setScope(session.beginScope())
  }, [session.selection?.epoch, session.selection?.taskId, session.beginScope])

  const runOptions = useMemo(
    () => session.runs.map((run) => run.run_id),
    [session.runs],
  )

  /** 文件候选只来自当前选中的任务；快照已失效（换过任务）就清空，绝不用别的任务的列表。 */
  function optionsFor(field: CapabilityField): string[] {
    if (field.name === 'run_dir') return runOptions
    if (field.kind === 'file') {
      const suffix = field.suffix
      if (!session.isCurrent(scope)) return []
      const pool = session.files
      const matching = pool.filter((file) => !suffix || file.suffix === suffix)
      return (matching.length > 0 ? matching : pool).map((file) => file.file_id)
    }
    return field.options
  }

  /**
   * 审批文件候选：inputs/ 里**导入**的既有审批 + 本任务 approvals/ 下由网页具名人审
   * **生成**的审批（文件名 = <profile_id>.json）。两类来源服务端都會复核来源，
   * 这里只是把可选项列全，不因为来源不同就藏起来。
   */
  function approvalOptions(): string[] {
    if (!session.isCurrent(scope)) return []
    const imported = session.files
      .filter((file) => file.suffix === '.json')
      .map((file) => file.file_id)
    const generated = session.profiles
      .filter((profile) => profile.approval_sha256)
      .map((profile) => `${profile.profile_id}.json`)
    return [...new Set([...generated, ...imported])]
  }

  async function submit() {
    setMessage('')
    // 提交前把这一刻的作用域固定下来：参数来自哪个任务，运行就登记到哪个任务
    const target = session.beginScope()
    if (!target) {
      setMessage('请先选择项目与任务')
      return
    }
    if (!session.isCurrent(target)) {
      setMessage('选择已变化，请重新确认参数后再提交')
      return
    }
    const params: Record<string, unknown> = {}
    for (const field of capability.fields) {
      const raw = values[field.name] ?? ''
      if (field.required && raw.trim() === '') {
        setMessage(`缺少必填项：${field.label}`)
        return
      }
      if (raw.trim() === '' && !field.required) continue
      if (field.kind === 'number') params[field.name] = Number(raw)
      else if (field.kind === 'list') params[field.name] = raw.split(/\s+/).filter(Boolean)
      else if (field.kind === 'box') params[field.name] = raw.split(/\s+/).filter(Boolean).map(Number)
      else params[field.name] = raw
    }
    try {
      const record = await session.runTool(capability.tool_id, params)
      if (record.status === 'blocked') {
        setMessage(record.error || '该能力当前不可用')
      } else {
        setMessage(`已提交 ${record.run_id}（${record.status}），归属 ${target.projectId}/${target.taskId}。`)
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <article className={`cap-card${capability.available ? '' : ' unavailable'}`}>
      <header className="cap-head">
        <div>
          <h3>{capability.label}</h3>
          <p className="muted small">合同：{capability.contract}</p>
        </div>
        <span className={capability.available ? 'badge badge-ok' : 'badge badge-warn'}>
          {capability.available ? '可用' : '不可用'}
        </span>
      </header>
      <p className="cap-desc">{capability.description}</p>
      {!capability.available && <p className="warn-text">不可用原因：{capability.reason}</p>}

      <div className="cap-fields">
        {capability.fields.map((field) => (
          <label key={field.name} className="field">
            <span className="field-label">
              {field.label}
              {field.required && <em className="required">*</em>}
            </span>
            {field.kind === 'select' ? (
              <select
                value={values[field.name] ?? ''}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                disabled={!capability.available}
              >
                {optionsFor(field).length === 0 && <option value="">（无可选项）</option>}
                {optionsFor(field).map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            ) : field.name === 'approval_file' ? (
              <select
                value={values[field.name] ?? ''}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                disabled={!capability.available}
              >
                <option value="">（选择人审审批文件）</option>
                {approvalOptions().map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            ) : field.kind === 'file' ? (
              <select
                value={values[field.name] ?? ''}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                disabled={!capability.available}
              >
                <option value="">（选择本任务输入文件）</option>
                {optionsFor(field).map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            ) : (
              <input
                type={field.kind === 'number' ? 'number' : 'text'}
                value={values[field.name] ?? ''}
                placeholder={field.help}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
                disabled={!capability.available}
              />
            )}
            {field.help && <span className="field-help muted small">{field.help}</span>}
          </label>
        ))}
      </div>

      <div className="cap-actions">
        <button type="button" className="primary" onClick={() => void submit()} disabled={!capability.available || session.busy !== ''}>
          {session.busy === capability.tool_id ? '提交中…' : '运行'}
        </button>
        <span className="muted small">输出：{capability.outputs.join('、')}</span>
      </div>
      {message && <p className="cap-message">{message}</p>}

      {session.runs.filter((run) => run.tool_id === capability.tool_id).slice(0, 3).map((run) => (
        <div key={run.run_id} className="run-line">
          <code>{run.run_id}</code>
          <StatusBadge status={run.status} />
          <span className="muted small">exit={run.exit_code ?? '—'} · {run.duration_sec ?? '—'}s</span>
          <button type="button" className="chip" onClick={() => session.setActiveRun(run.run_id)}>查看</button>
        </div>
      ))}
    </article>
  )
}
