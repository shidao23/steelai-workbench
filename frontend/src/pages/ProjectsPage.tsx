import { useState } from 'react'
import { useSession } from '../state/session'
import { EmptyState, StatusBadge } from '../components/ui'

export function ProjectsPage() {
  const session = useSession()
  const [newTaskId, setNewTaskId] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [note, setNote] = useState('')
  const [message, setMessage] = useState('')

  const project = session.projects.find((item) => item.project_id === session.projectId)

  async function submit() {
    setMessage('')
    if (!newTaskId.trim()) {
      setMessage('请填写任务标识（英文/数字，例如 T002_unit_check）')
      return
    }
    try {
      await session.createTask(newTaskId.trim(), newTitle.trim() || newTaskId.trim(), note.trim())
      setMessage(`已创建任务 ${newTaskId.trim()}`)
      setNewTaskId('')
      setNewTitle('')
      setNote('')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>项目</h2>
        <p className="muted">
          项目清单直接读现有科研登记（科研主表 <code>项目表</code>），不新建第二个总项目库；
          合成演示项目用于本批隔离测试。
        </p>
      </div>

      <section className="panel">
        <h3>选择项目</h3>
        {session.projects.length === 0 && (
          <EmptyState title="没有读到项目" hint="科研主表不可读或没有项目行；合成项目会在首次创建任务时出现。" />
        )}
        <div className="project-grid">
          {session.projects.map((item) => (
            <button
              type="button"
              key={item.project_id}
              className={item.project_id === session.projectId ? 'project-card active' : 'project-card'}
              onClick={() => session.selectProject(item.project_id)}
            >
              <div className="project-id">{item.project_id}</div>
              <div className="project-name">{item.short_name || item.directory_name || '（未命名）'}</div>
              <div className="muted small">状态：{item.status || '—'} · 任务 {item.task_count}</div>
              {item.synthetic && <div className="badge badge-busy">合成</div>}
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h3>当前项目</h3>
        {!project && <EmptyState title="未选择项目" hint="先在上面选一个项目。" />}
        {project && (
          <dl className="kv">
            <dt>项目标识</dt><dd>{project.project_id}</dd>
            <dt>目录名</dt><dd>{project.directory_name || '—'}</dd>
            <dt>来源</dt><dd>{project.source || '—'}</dd>
            <dt>工作根</dt><dd><code>{project.root_exists ? '已建立' : '尚未建立（创建任务时生成）'}</code></dd>
          </dl>
        )}
      </section>

      <section className="panel">
        <h3>任务</h3>
        {project && project.tasks.length === 0 && (
          <EmptyState title="该项目还没有任务" hint="在下面新建一个任务，或先在别处建立 03_工作区/<项目>/<任务>/ 结构。" />
        )}
        <div className="task-list">
          {project?.tasks.map((task) => (
            <button
              type="button"
              key={task.task_id}
              className={task.task_id === session.taskId ? 'task-card active' : 'task-card'}
              onClick={() => session.selectTask(task.task_id)}
            >
              <div>
                <div className="task-title">{task.title}</div>
                <div className="muted small">
                  <code>{task.task_id}</code> · 输入 {task.file_count} · 运行 {task.run_count}
                </div>
              </div>
              <span className="muted small">{task.created_at}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <h3>新建任务</h3>
        <div className="form-row">
          <label className="field">
            <span className="field-label">任务标识<em className="required">*</em></span>
            <input value={newTaskId} onChange={(event) => setNewTaskId(event.target.value)} placeholder="T002_unit_check" />
          </label>
          <label className="field">
            <span className="field-label">标题</span>
            <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="单位核对与预处理" />
          </label>
        </div>
        <label className="field">
          <span className="field-label">说明</span>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3}
                    placeholder="本任务要做什么、输入来自哪里、验收条件" />
        </label>
        <button type="button" className="primary" onClick={() => void submit()} disabled={session.busy !== ''}>
          创建任务
        </button>
        {message && <p className="cap-message">{message}</p>}
      </section>

      {session.runs.length > 0 && (
        <section className="panel">
          <h3>最近运行</h3>
          <ul className="run-list">
            {session.runs.slice(0, 6).map((run) => (
              <li key={run.run_id}>
                <code>{run.run_id}</code> <StatusBadge status={run.status} />
                <span className="muted small">{run.tool_label}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
