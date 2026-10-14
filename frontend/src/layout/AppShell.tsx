import { useMemo, useState, type ReactNode } from 'react'
import { useSession, type PageKey } from '../state/session'
import { usePanelsState } from './usePanelsState'

/**
 * WO-33 §3 — 本地人审配对条。
 *
 * 页面默认拿到的是**只读**会话；要上传/建任务/做具名人审，需要用服务启动窗口
 * （或本地配对文件）里的**一次性配对码**换一个带 ``review:human`` 的会话。
 * 配对码是一次性的、用过即轮换；这里只把它提交给本机回环服务，不落任何存储。
 */
function PairingBanner() {
  const session = useSession()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)

  if (session.paired) return null

  const submit = async () => {
    if (!code.trim()) return
    setBusy(true)
    try {
      const ok = await session.pair(code.trim())
      if (ok) setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="banner warn" role="status">
      <strong>未配对：当前是只读会话</strong>
      <p className="muted small">
        可以查看项目/任务/文件与运行记录，但<strong>不能</strong>上传、建任务或做具名人工确认。
        要解锁这些操作，请把服务启动窗口里打印的<strong>一次性配对码</strong>填到这里
        （同一份也写在本机文件 <code>{session.pairing?.file || 'outputs/research_web/session/pairing.txt'}</code>）。
        配对码用过即作废并自动轮换；它只是本机回环服务的本地凭据，请不要贴进聊天或截图。
      </p>
      <div className="row-inline">
        <input
          type="text"
          value={code}
          placeholder="8 位配对码"
          aria-label="一次性配对码"
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => setCode(event.target.value.toUpperCase())}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void submit()
          }}
        />
        <button type="button" className="primary" disabled={busy || !code.trim()} onClick={() => void submit()}>
          {busy ? '配对中…' : '配对并解锁人审'}
        </button>
        <button type="button" className="chip" disabled={busy} onClick={() => void session.useReadOnly()}>
          继续只读
        </button>
      </div>
      {session.pairError && <p className="problem">{session.pairError}</p>}
    </div>
  )
}

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
  const scopeLabel = session.selection
    ? `${session.selection.projectId}/${session.selection.taskId} · 世代 ${session.selection.epoch}`
    : '未选择'

  return (
    <div className={`shell${panels.collapsedLeft ? ' left-collapsed' : ''}${panels.collapsedRight ? ' right-collapsed' : ''}`}>
      <header className="topbar">
        <div className="brand">
          <strong>SteelAI 科研工作台</strong>
          <span className="muted small">React 六页 · 薄 API · 现有工具</span>
        </div>
        <div className="topbar-context">
          {session.needsReselect && (
            <span className="context-chip warn" title="刷新后没有恢复上次选择，或上次的任务已不存在">
              请重新选择项目与任务
            </span>
          )}
          <span className="context-chip">
            项目 <b>{project ? `${project.project_id}${project.short_name ? ` · ${project.short_name}` : ''}` : '未选择'}</b>
          </span>
          <span className="context-chip">
            当前任务 <b>{task ? `${task.task_id}` : '未选择'}</b>
          </span>
          <span className="context-chip muted" title="作用域世代：每次切换 +1，迟到的响应一律丢弃">
            {scopeLabel}
          </span>
          <span
            className={session.paired ? 'context-chip' : 'context-chip warn'}
            title={
              session.paired
                ? '已配对的人审会话：本地一次性配对码换取，含具名人审能力'
                : '只读会话：可读/建议；不能人审、不能写任务与上传（需本地配对码解锁）'
            }
          >
            {session.paired ? '已配对 · 可人审' : '只读会话'}
          </span>
          <button type="button" className="chip" onClick={() => void session.refreshAll()}>
            刷新
          </button>
        </div>
      </header>

      <PairingBanner />

      {session.needsReselect && (
        <div className="banner warn" role="status">
          刷新后没有恢复上次的项目/任务（或它已不存在）。为避免把上一轮的结果显示到别的任务上，
          请到「项目」页显式选择；这里不会替你默认选一个。
        </div>
      )}

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
      </footer>    </div>
  )
}
