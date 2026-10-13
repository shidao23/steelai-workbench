import { useMemo, useState } from 'react'
import { useSession } from '../state/session'
import { ToolRunner } from '../components/ToolRunner'
import { EmptyState } from '../components/ui'
import { IframePanel } from '../iframe/IframePanel'

export function ToolsPage() {
  const session = useSession()
  const [showResearchPage, setShowResearchPage] = useState(true)
  const caps = useMemo(
    () => session.capabilities.filter((cap) => cap.page === 'tools'),
    [session.capabilities],
  )

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
          该页没有实现消息协议时按普通 iframe 嵌入，仅显示原页，不当作数据/AI 已接通。
        </p>
        {showResearchPage && (
          session.researchAppUrl
            ? (
              <IframePanel
                title="科研工作台（Streamlit 原页）"
                url={session.researchAppUrl}
                allowedOrigins={session.allowedOrigins}
                projectId={session.projectId}
                taskId={session.taskId}
                note={`固定可信端口；当前项目 ${session.projectId || '未选择'} / 任务 ${session.taskId || '未选择'}`}
              />
            )
            : <EmptyState title="科研页地址未知" hint="薄 API 的 /api/health 未返回 research_app_url。" />
        )}
      </section>
    </div>
  )
}
