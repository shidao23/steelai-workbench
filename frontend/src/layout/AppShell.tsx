import { useMemo, type ReactNode } from 'react'
import { useSession, type PageKey } from '../state/session'
import { usePanelsState } from './usePanelsState'

const NAV: { key: PageKey; label: string; hint: string }[] = [
  { key: 'projects', label: '项目', hint: '项目/任务选择与当前进度' },
  { key: 'files', label: '资料', hint: '本项目文件、上传与预览' },
  { key: 'data_processing', label: '数据处理', hint: '映射/单位、人审、运行与 QC' },
  { key: 'tools', label: '分析工具', hint: '统计 / 图像分割 / 相变计算' },
  { key: 'artifacts', label: '成果', hint: '表、图、报告包与下载' },
  { key: 'work_log', label: '工作记录', hint: '参数、执行、来源与接手' },
]

export function AppShell({ children, aiPanel }: { children: ReactNode; aiPanel: ReactNode }) {
  const session = useSession()
  const { panels, update, resetPanels } = usePanelsState(session.projectId, session.page)

  const project = useMemo(
    () => session.projects.find((item) => item.project_id === session.projectId),
    [session.projects, session.projectId],
  )
  const task = useMemo(
    () => project?.tasks.find((item) => item.task_id === session.taskId),
    [project, session.taskId],
  )

  return (
    <div className={`shell${panels.collapsedLeft ? ' left-collapsed' : ''}${panels.collapsedRight ? ' right-collapsed' : ''}`}>
      <header className="topbar">
        <div className="brand">
          <strong>SteelAI 科研工作台</strong>
          <span className="muted small">React 六页 · 薄 API · 现有工具</span>
        </div>
        <div className="topbar-context">
          <span className="context-chip">
            项目 <b>{project ? `${project.project_id}${project.short_name ? ` · ${project.short_name}` : ''}` : '未选择'}</b>
          </span>
          <span className="context-chip">
            当前任务 <b>{task ? `${task.task_id}` : '未选择'}</b>
          </span>
          <button type="button" className="chip" onClick={() => void session.refreshAll()}>
            刷新
          </button>
        </div>
      </header>

      <div className="shell-body">
        <nav className={`leftnav${panels.left ? '' : ' hidden'}`} aria-label="主导航">
          <button
            type="button"
            className="nav-toggle"
            onClick={() => update({ collapsedLeft: !panels.collapsedLeft })}
            aria-expanded={!panels.collapsedLeft}
          >
            {panels.collapsedLeft ? '展开导航' : '收起导航'}
          </button>
          {!panels.collapsedLeft && (
            <>
              <ul className="nav-list">
                {NAV.map((item) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      className={item.key === session.page ? 'nav-item active' : 'nav-item'}
                      onClick={() => session.setPage(item.key)}
                      title={item.hint}
                    >
                      <span className="nav-label">{item.label}</span>
                      <span className="nav-hint">{item.hint}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <div className="nav-foot">
                <span className="muted small">布局状态键：{session.page}</span>
                <button type="button" className="chip" onClick={resetPanels}>重置栏位</button>
              </div>
            </>
          )}
        </nav>

        <main className="center" role="main">
          {children}
        </main>

        <aside className={`rightbar${panels.collapsedRight ? ' collapsed' : ''}`} aria-label="AI 工作栏">
          <div className="rightbar-head">
            <strong>AI 工作</strong>
            <button
              type="button"
              className="chip"
              onClick={() => update({ collapsedRight: !panels.collapsedRight })}
            >
              {panels.collapsedRight ? '展开' : '收起'}
            </button>
          </div>
          {!panels.collapsedRight && aiPanel}
        </aside>
      </div>

      <footer className="statusbar">
        <span>工作区：{session.workRoot || '—'}</span>
        <span>任务：{session.taskId || '—'}</span>
        <span>{session.busy ? `进行中：${session.busy}` : '空闲'}</span>
      </footer>
    </div>
  )
}
