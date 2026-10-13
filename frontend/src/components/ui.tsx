import type { ReactNode } from 'react'

export function StatusBadge({ status }: { status: string }) {
  const tone = status === 'succeeded' ? 'ok'
    : status === 'failed' || status === 'timeout' ? 'bad'
    : status === 'blocked' ? 'warn'
    : status === 'running' || status === 'queued' ? 'busy'
    : 'idle'
  const label: Record<string, string> = {
    succeeded: '成功',
    failed: '失败',
    timeout: '超时',
    blocked: '不可用',
    running: '运行中',
    queued: '排队中',
  }
  return <span className={`badge badge-${tone}`}>{label[status] ?? status}</span>
}

export function EmptyState({ title, hint, action }: { title: string; hint: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span className="muted">{hint}</span>
      {action}
    </div>
  )
}

export function ErrorBanner({ message, onClose }: { message: string; onClose: () => void }) {
  if (!message) return null
  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      <button type="button" className="chip" onClick={onClose}>关闭</button>
    </div>
  )
}

export function DataTable({ columns, rows, max = 200 }: { columns: string[]; rows: (string | number)[][]; max?: number }) {
  if (columns.length === 0) {
    return <EmptyState title="没有可显示的列" hint="该文件没有解析出表头。" />
  }
  const shown = rows.slice(0, max)
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>{columns.map((column, index) => <th key={`${column}-${index}`}>{column || `列${index + 1}`}</th>)}</tr>
        </thead>
        <tbody>
          {shown.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {columns.map((_, cellIndex) => (
                <td key={cellIndex}>{String(row[cellIndex] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown.length && (
        <p className="muted small">仅显示前 {shown.length} / {rows.length} 行，完整内容请下载原文件。</p>
      )}
    </div>
  )
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}
