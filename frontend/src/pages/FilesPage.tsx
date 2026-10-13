import { useEffect, useState } from 'react'
import { api, type Preview } from '../api/client'
import { useSession } from '../state/session'
import { DataTable, EmptyState, formatBytes } from '../components/ui'

export function FilesPage() {
  const session = useSession()
  const [preview, setPreview] = useState<Preview | null>(null)
  const [previewName, setPreviewName] = useState('')
  const [previewError, setPreviewError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setPreview(null)
    setPreviewName('')
    setPreviewError('')
  }, [session.taskId])

  async function openPreview(fileId: string) {
    setPreviewError('')
    setBusy(true)
    try {
      const result = await api.preview(session.projectId, session.taskId, fileId)
      setPreview(result)
      setPreviewName(fileId)
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : String(error))
      setPreview(null)
    } finally {
      setBusy(false)
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return
    setPreviewError('')
    for (const file of Array.from(files)) {
      try {
        await session.uploadFile(file)
      } catch (error) {
        setPreviewError(`${file.name}：${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>资料</h2>
        <p className="muted">
          本任务输入目录 <code>inputs/</code>。原件只读，不扫描全库；上传名会被服务端规整为单一文件名，
          拒绝 <code>../</code>、盘符、设备名与非法类型。
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
      </section>

      <section className="panel">
        <h3>本任务文件（{session.files.length}）</h3>
        {session.files.length === 0 && (
          <EmptyState title="还没有输入文件" hint="上传一个 csv/json/png 等文件后即可预览。" />
        )}
        {session.files.length > 0 && (
          <table className="data-table">
            <thead>
              <tr><th>文件</th><th>类型</th><th>大小</th><th>修改时间</th><th>操作</th></tr>
            </thead>
            <tbody>
              {session.files.map((file) => (
                <tr key={file.file_id}>
                  <td>{file.name}</td>
                  <td>{file.suffix}</td>
                  <td>{formatBytes(file.size)}</td>
                  <td>{file.modified}</td>
                  <td className="row-actions">
                    <button type="button" className="chip" disabled={busy}
                            onClick={() => void openPreview(file.file_id)}>预览</button>
                    <button type="button" className="chip danger"
                            onClick={() => void session.deleteFile(file.file_id)}>删除</button>
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
              分隔符 <code>{preview.delimiter === '\t' ? '\\t' : preview.delimiter}</code> ·
              共 {preview.total_lines} 行{preview.truncated ? '（已截断）' : ''}
            </p>
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
            <p className="muted small">工作表：{preview.sheets.join('、')}（预览 {preview.sheet}）</p>
            <DataTable columns={preview.columns} rows={preview.rows} />
          </>
        )}
        {preview?.kind === 'binary' && <p className="muted">{preview.note}</p>}
      </section>
    </div>
  )
}
