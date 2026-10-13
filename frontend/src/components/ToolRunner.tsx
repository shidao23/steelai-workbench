import { useMemo, useState } from 'react'
import type { Capability, CapabilityField } from '../api/client'
import { useSession } from '../state/session'
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

  const runOptions = useMemo(
    () => session.runs.map((run) => run.run_id),
    [session.runs],
  )

  function optionsFor(field: CapabilityField): string[] {
    if (field.name === 'run_dir') return runOptions
    if (field.kind === 'file') {
      const suffix = field.suffix
      const matching = session.files.filter((file) => !suffix || file.suffix === suffix)
      return (matching.length > 0 ? matching : session.files).map((file) => file.file_id)
    }
    return field.options
  }

  async function submit() {
    setMessage('')
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
        setMessage(`已提交 ${record.run_id}（${record.status}），可在“工作记录”或右栏查看。`)
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
