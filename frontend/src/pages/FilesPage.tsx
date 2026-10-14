import { useEffect, useState } from 'react'
import { api, type Preview } from '../api/client'
import { useSession, type Scope } from '../state/session'
import { DataTable, EmptyState, formatBytes } from '../components/ui'

/**
 * WO-32 §2/§3 — 资料页。
 * * 预览用带 epoch 的快照：换任务/项目后迟到的预览一律丢弃，不会把别任务的内容显示在这里。
 * * CSV/TSV/XLSX 走后端 `tabular.read_table`（逻辑记录、引号、BOM、不齐列如实报告），
 *   与后续映射/运行是同一套解释；编码损坏会明确报错，不会悄悄替换字符。
 */
export function FilesPage() {
  const session = useSession()
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewName, setPreviewName] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [busy, setBusy] = useState(false)
  const [scope, setScope] = useState<Scope | null>(() => session.beginScope())
  const [message, setMessage] = useState('')
  const [sheet, setSheet] = useState('')

  useEffect(() => {
    setScope(session.beginScope())
  }, [session.selection?.epoch, session.selection?.taskId, session.beginScope])

  useEffect(() => {
    setPreview(null)
    setPreviewName('')
    setPreviewError('')
    setMessage('')
  }, [session.selection?.epoch, session.selection?.taskId])

  async function openPreview(fileId: string, sheetOverride?: string) {
    if (!scope || !session.isCurrent(scope)) {
      setPreviewError('选择已变化，请重新选择文件')
      return
    }
    setPreviewError('')
    setMessage('')
    setBusy(true)
    const wanted = sheetOverride ?? sheet
    try {
      const result = await api.preview(scope.projectId, scope.taskId, fileId,
        { sheet: wanted || undefined })
      if (!session.isCurrent(scope)) return   // 迟到的响应：丢弃
      setPreview(result)
      setPreviewName(fileId)
      if (result.sheet) setSheet(result.sheet)
      if (result.kind === 'error') {
        setPreviewError(result.problem ?? '该文件无法解析。')
      }
    } catch (error) {
      if (!session.isCurrent(scope)) return
      setPreviewError(error instanceof Error ? error.message : String(error))
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return
    setPreviewError('')
    setMessage('')
    for (const file of Array.from(files)) {
      try {
        await session.uploadFile(file)
        setMessage(`已上传 ${file.name}；服务端记录了上传字节的 SHA-256。`)
      } catch (error) {
        setPreviewError(`${file.name}：${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }

  async function remove(fileId: string) {
    if (!window.confirm(`删除本任务输入 ${fileId}？删除只影响本任务 inputs/，原件不可恢复。`)) return
    setMessage('')
    try {
      await session.deleteFile(fileId)
      setMessage(`已删除 ${fileId}`)
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error))
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>资料</h2>
        <p className="muted">
          本任务输入目录 <code>inputs/</code>。原件只读，不扫描全库；上传名会被服务端规整为单一文件名，
          拒绝 <code>../</code>、盘符、设备名与非法类型；重名会被拒绝而不是静默覆盖。
        </p>
      </div>

      <section className="panel">
        <h3>上传到本任务</h3>
        {!session.taskId && <EmptyState title="未选择任务" hint="请先在“项目”页选择一个任务。" />}
        {session.taskId && (
          <>
            <input type="file" multiple onChange={(event) => void onUpload(event.target.files)} />
            <p className="muted small">
              允许：csv/tsv/txt/json/md/png/jpg/tif/bmp/xlsx/xls/yaml/yml，单个 ≤ 64 MB，重名会被拒绝。
            </p>
          </>
        )}
        {previewError && <p className="warn-text">{previewError}</p>}
        {message && <p className="cap-message">{message}</p>}
      </section>

      <section className="panel">
        <h3>本任务文件（{session.files.length}）</h3>
        {session.files.length === 0 && (
          <EmptyState title="还没有输入文件" hint="上传一个 csv/json/png 等文件后即可预览。" />
        )}
        {session.files.length > 0 && (
          <table className="data-table">
            <thead>
              <tr><th>文件</th><th>类型</th><th>大小</th><th>SHA-256</th><th>修改时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              {session.files.map((file) => (
                <tr key={file.file_id}>
                  <td>{file.name}</td>
                  <td>{file.suffix}</td>
                  <td>{formatBytes(file.size)}</td>
                  <td><code className="hash" title={file.sha256 ?? ''}>
                    {file.sha256 ? `${file.sha256.slice(0, 12)}…` : '—'}
                  </code></td>
                  <td>{file.modified}</td>
                  <td className="row-actions">
                    <button type="button" className="chip" disabled={busy}
                            onClick={() => void openPreview(file.file_id)}>预览</button>
                    <button type="button" className="chip" onClick={() => { session.setPage('data_processing') }}>
                      用于映射
                    </button>
                    <button type="button" className="chip danger"
                            onClick={() => void remove(file.file_id)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3>预览{previewName ? ` · ${previewName}` : ''}</h3>
        {!preview && <EmptyState title="未选择文件" hint="点击上表“预览”，只读展示表头、单位与来源。" />}
        {preview?.kind === 'table' && (
          <>
            <p className="muted small">
              分隔符 <code>{preview.delimiter === '\t' ? '\\t' : preview.delimiter}</code>（按扩展名判定，不猜）·
              {preview.records ?? 0} 条逻辑记录
              {preview.physical_lines && preview.physical_lines !== preview.records
                ? `（文件物理行 ${preview.physical_lines}；引号内换行按 1 条记录算）`
                : ''}
              {preview.truncated ? ' · 仅显示前若干行' : ''}
            </p>
            {(preview.ragged_rows?.length ?? 0) > 0 && (
              <p className="warn-text">
                有 {preview.ragged_rows?.length} 行列数与表头不一致（第 {preview.ragged_rows?.slice(0, 5).join('、')} 行…）——映射前需先修数据。
              </p>
            )}
            {(preview.duplicate_headers?.length ?? 0) > 0 && (
              <p className="warn-text">重复表头：{preview.duplicate_headers?.join('、')}</p>
            )}
            {preview.has_formulas && (
              <p className="warn-text">该工作簿含公式：这里显示的是缓存值，SteelData 运行要求"仅值"导出。</p>
            )}
            <DataTable columns={preview.columns} rows={preview.rows} />
          </>
        )}
        {preview?.kind === 'json' && (
          <pre className="code-block">{JSON.stringify(preview.json_head, null, 2)}</pre>
        )}
        {preview?.kind === 'text' && <pre className="code-block">{preview.text}</pre>}
        {preview?.kind === 'image' && (
          <p className="muted">
            {preview.image.format} · {preview.image.width}×{preview.image.height} px。
            {preview.note} 图像可直接用于 Micro-SAM 单图分割。
          </p>
        )}
        {preview?.kind === 'workbook' && (
          <>
            <p className="muted small">
              工作表：{(preview.sheets ?? []).join('、')}（预览 {preview.sheet}）· 表头第 {preview.header_row ?? 1} 行 ·
              {preview.records ?? 0} 条逻辑记录
              {preview.sheet_required
                ? ' · 多工作表：映射时必须显式选定 sheet，否则 SteelData 会拒绝运行'
                : ''}
            </p>
            {(preview.sheets ?? []).length > 1 && (
              <div className="form-row">
                <label className="field">
                  <span className="field-label">预览工作表</span>
                  <select
                    value={preview.sheet ?? ''}
                    onChange={(event) => void openPreview(previewName, event.target.value)}
                  >
                    {(preview.sheets ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                </label>
              </div>
            )}
            {preview.has_formulas && (
              <p className="warn-text">
                该工作簿含公式：SteelData 会拒绝这种文件，需先另存为「仅值」版本。
                下表是 SteelData 读到的内容；缓存值仅作辨认，不是运行会读到的数据。
              </p>
            )}
            <DataTable columns={preview.columns} rows={preview.rows} />
            {preview.has_formulas && (preview.cached_rows ?? []).length > 0 && (
              <>
                <p className="muted small">Excel 缓存的公式结果（仅供辨认）：</p>
                <DataTable columns={preview.columns} rows={preview.cached_rows ?? []} />
              </>
            )}
          </>
        )}
        {preview?.kind === 'binary' && <p className="muted">{preview.note}</p>}
      </section>
    </div>
  )
}
