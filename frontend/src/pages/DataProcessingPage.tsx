import { useMemo } from 'react'
import { useSession } from '../state/session'
import { ToolRunner } from '../components/ToolRunner'
import { GridLayout } from '../layout/GridLayout'
import { RunDetail } from '../components/RunDetail'
import { EmptyState } from '../components/ui'

export function DataProcessingPage() {
  const session = useSession()
  const caps = useMemo(
    () => session.capabilities.filter((cap) => cap.page === 'data_processing'),
    [session.capabilities],
  )
  const active = session.runs.find((run) => run.run_id === session.activeRunId) ?? session.runs[0] ?? null

  return (
    <div className="page">
      <div className="page-head">
        <h2>数据处理</h2>
        <p className="muted">
          复用 SteelData 的治理合同：<b>预览</b>只读不改数据；<b>按人审运行</b>必须提供显式人工审批文件
          （上传到“资料”页）；未知单位、身份或摘要变化会停在 <code>needs_human</code>，合成演示里的坏值按原合同
          <code>QCfailed</code>，不会改绿。
        </p>
      </div>

      <GridLayout
        projectId={session.projectId}
        page={session.page}
        primaryLabel="数据处理能力"
        secondaryLabel="运行结果"
        primary={
          <div className="cap-list">
            {caps.length === 0 && <EmptyState title="没有数据处理能力" hint="薄 API 未返回 data_processing 能力。" />}
            {caps.map((cap) => <ToolRunner key={cap.tool_id} capability={cap} />)}
          </div>
        }
        secondary={
          active
            ? <RunDetail run={active} />
            : <EmptyState title="还没有运行" hint="在上面选一个能力并点“运行”，结果会出现在这里。" />
        }
      />
    </div>
  )
}
