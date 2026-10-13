import { useMemo, useState } from 'react'
import { artifactUrl } from '../api/client'
import { useSession } from '../state/session'
import { StatusBadge } from './ui'

/**
 * 右栏“AI 工作”。这里只提供**真实**内容：
 * 任务上下文、来源与限制、执行记录、待人工确认事项、接手导出。
 * 没有接通的云会话就不显示聊天输入框——不伪造“在线聊天”。
 */
export function AiPanel() {
  const session = useSession()
  const [copied, setCopied] = useState('')

  const pendingHuman = useMemo(
    () => session.runs.filter((run) => run.status === 'blocked' || run.status === 'failed' || run.status === 'timeout'),
    [session.runs],
  )

  const limits = useMemo(() => [
    '未知单位 / 身份 / 摘要变化 → needs_human，不自动改绿。',
    '合成演示里的坏值按原合同 QCfailed，不视为启动失败。',
    'Micro-SAM 坐标是原像素；缺权重或环境时该卡不可用。',
    'CALPHAD 首版只做已验证缩减体系；真实 B/R 曲线仍 blocked。',
    '候选成果不自动 accepted；晋升要接原 owner 人审。',
  ], [])

  function exportHandoff() {
    const lines = [
      `# 接手摘要（导出）`,
      ``,
      `- project_id: ${session.projectId || '未选择'}`,
      `- task_id: ${session.taskId || '未选择'}`,
      `- 导出时间: ${new Date().toISOString()}`,
      ``,
      `## 运行记录`,
      ...session.runs.map((run) => `- ${run.run_id} · ${run.tool_label} · ${run.status} · exit=${run.exit_code ?? '—'}`),
      ``,
      `## 产物`,
      ...session.artifacts.map((item) => `- ${item.run_id}/${item.rel} (${item.size} B, sha256 ${item.sha256.slice(0, 16)}…)`),
      ``,
      `## 待人工确认`,
      ...(pendingHuman.length > 0
        ? pendingHuman.map((run) => `- ${run.run_id} · ${run.tool_label} · ${run.error || run.status}`)
        : ['- 无']),
      ``,
      `## 限制`,
      ...limits.map((item) => `- ${item}`),
    ]
    const text = lines.join('\n')
    navigator.clipboard?.writeText(text).then(
      () => setCopied('已复制到剪贴板'),
      () => setCopied('复制失败，可手动从“工作记录”导出'),
    )
  }

  return (
    <div className="ai-panel">
      <section>
        <h4>任务上下文</h4>
        <dl className="kv small">
          <dt>项目</dt><dd>{session.projectId || '—'}</dd>
          <dt>任务</dt><dd>{session.taskId || '—'}</dd>
          <dt>输入</dt><dd>{session.files.length} 个文件</dd>
          <dt>运行</dt><dd>{session.runs.length} 次</dd>
        </dl>
      </section>

      <section>
        <h4>来源与限制</h4>
        <ul className="tight">
          {limits.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <section>
        <h4>执行记录</h4>
        {session.runs.length === 0 && <p className="muted small">尚未运行。</p>}
        <ul className="tight">
          {session.runs.slice(0, 8).map((run) => (
            <li key={run.run_id}>
              <code>{run.run_id}</code> <StatusBadge status={run.status} />
              <div className="muted small">{run.tool_label}</div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>待人事项（{pendingHuman.length}）</h4>
        {pendingHuman.length === 0
          ? <p className="muted small">没有需要人工确认的运行。</p>
          : (
            <ul className="tight">
              {pendingHuman.map((run) => (
                <li key={run.run_id}>
                  <code>{run.run_id}</code>
                  <div className="warn-text small">{run.error || run.status}</div>
                </li>
              ))}
            </ul>
          )}
      </section>

      <section>
        <h4>最近产物</h4>
        {session.artifacts.length === 0 && <p className="muted small">无产物。</p>}
        <ul className="tight">
          {session.artifacts.slice(0, 6).map((artifact) => (
            <li key={`${artifact.run_id}-${artifact.rel}`}>
              <a href={artifactUrl(artifact.run_id ?? '', artifact.rel)} download>{artifact.name}</a>
              <div className="muted small">{artifact.tool_label}</div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>接手导出</h4>
        <button type="button" className="chip" onClick={exportHandoff}>复制接手摘要</button>
        {copied && <p className="muted small">{copied}</p>}
        <p className="muted small">
          另一个 AI 读同一 README、同一任务目录与 handoff.md 即可接续；本栏不连接云模型，
          也不伪造在线聊天。
        </p>
      </section>
    </div>
  )
}
