import { useEffect, useMemo, useState } from 'react'
import { api, type ResearchUrl } from '../api/client'
import { useSession, type Scope } from '../state/session'
import { ToolRunner } from '../components/ToolRunner'
import { EmptyState } from '../components/ui'
import { IframePanel } from '../iframe/IframePanel'

/**
 * WO-32 §3 — 分析工具页 + 科研旧页（Streamlit）嵌入。
 *
 * iframe 地址**必须**来自服务端 `.../research-url`：它按当前 project/task 构建，
 * 并经服务端 registry 校验，所以页面无法把 iframe 指向任意地址；切换项目/任务会
 * 得到一个新的、重新校验过的 URL，iframe 随之重载、旧绑定失效。
 */
export function ToolsPage() {
  const session = useSession()
  const [showResearchPage, setShowResearchPage] = useState(true)
  const [research, setResearch] = useState<ResearchUrl | null>(null)
  const [researchError, setResearchError] = useState('')
  const [scope, setScope] = useState<Scope | null>(() => session.beginScope())
  const caps = useMemo(
    () => session.capabilities.filter((cap) => cap.page === 'tools'),
    [session.capabilities],
  )

  useEffect(() => {
    setScope(session.beginScope())
  }, [session.selection?.epoch, session.selection?.taskId, session.beginScope])

  useEffect(() => {
    if (!scope || !session.isCurrent(scope)) {
      setResearch(null)
      return
    }
    let alive = true
    setResearchError('')
    void (async () => {
      try {
        const result = await api.researchUrl(scope.projectId, scope.taskId)
        if (alive && session.isCurrent(scope)) setResearch(result)
      } catch (error) {
        if (alive && session.isCurrent(scope)) {
          setResearch(null)
          setResearchError(error instanceof Error ? error.message : String(error))
        }
      }
    })()
    return () => {
      alive = false
    }
  }, [scope, session])

  return (
    <div className="page">
      <div className="page-head">
        <h2>分析工具</h2>
        <p className="muted">
          每个工具保持自己的独立环境与固定 CLI 合同，缺一个工具只让对应卡片不可用，
          不影响其它工具。统计不做显著性，图像坐标是原像素，相变首版只做已验证的缩减体系。
        </p>
      </div>

      <div className="cap-list">
        {caps.length === 0 && <EmptyState title="没有工具能力" hint="薄 API 未返回 tools 能力。" />}
        {caps.map((cap) => <ToolRunner key={cap.tool_id} capability={cap} />)}
      </div>

      <section className="panel">
        <header className="panel-head">
          <h3>科研旧页（Streamlit）</h3>
          <button type="button" className="chip" onClick={() => setShowResearchPage((value) => !value)}>
            {showResearchPage ? '隐藏' : '显示'}
          </button>
        </header>
        <p className="muted small">
          科研专用薄入口 <code>research_app.py</code> 只登记已确认的科研页，不嵌原 PAOS/生活混合首页。
          地址由服务端按当前项目/任务构建；该页没有实现消息协议时按普通 iframe 嵌入，
          仅显示原页，不当作数据/AI 已接通。
        </p>
        {showResearchPage && (
          research
            ? (
              <IframePanel
                title="科研工作台（Streamlit 原页）"
                url={research.url}
                allowedOrigins={session.allowedOrigins}
                projectId={research.project_id}
                taskId={research.task_id}
                note={`服务端校验地址；当前项目 ${research.project_id} / 任务 ${research.task_id}`}
              />
            )
            : <EmptyState
                title={session.taskId ? '科研页地址不可用' : '未选择任务'}
                hint={researchError
                  || (session.taskId
                    ? '服务端没有为该任务返回可用的科研页地址；请先启动 Start_Research_Streamlit.cmd。'
                    : '请先在“项目”页选择任务——科研旧页的地址按项目/任务构建。')}
              />
        )}
      </section>
    </div>
  )
}
