import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  type Capability,
  type CandidateProfile,
  type DescribeInput,
  type InputColumn,
  type MappingContract,
  type ReviewEntry,
} from '../api/client'
import { useSession, type Scope } from '../state/session'
import { ToolRunner } from '../components/ToolRunner'
import { GridLayout } from '../layout/GridLayout'
import { RunDetail } from '../components/RunDetail'
import { EmptyState, formatBytes } from '../components/ui'

interface MappingRow {
  source: string
  target: string
  unit: string
  required: boolean
}

const DOMAIN_LABEL: Record<string, string> = {
  tensile: ' tensile · 拉伸性能（MPa/%）',
  tensile_curve: 'tensile_curve · 拉伸曲线（N/mm/s）',
  composition: 'composition · 成分（堆叠报表，需原 CLI）',
}

export function DataProcessingPage() {
  const session = useSession()
  const caps = useMemo(
    () => session.capabilities.filter((cap) => cap.page === 'data_processing'),
    [session.capabilities],
  )
  const active = session.runs.find((run) => run.run_id === session.activeRunId) ?? session.runs[0] ?? null

  const [contract, setContract] = useState<MappingContract | null>(null)
  const [scope, setScope] = useState<Scope | null>(() => session.beginScope())
  const [fileId, setFileId] = useState('')
  const [described, setDescribed] = useState<DescribeInput | null>(null)
  const [describeError, setDescribeError] = useState('')
  const [domain, setDomain] = useState('tensile')
  const [layout, setLayout] = useState('flat')
  const [headerRow, setHeaderRow] = useState('1')
  const [profileId, setProfileId] = useState('')
  const [rows, setRows] = useState<MappingRow[]>([])
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<Record<string, unknown> | null>(null)
  const [previewResult, setPreviewResult] = useState<Record<string, unknown> | null>(null)
  const [saveError, setSaveError] = useState('')

  const [reviewer, setReviewer] = useState('')
  const [note, setNote] = useState('')
  const [synthetic, setSynthetic] = useState(true)
  const [reviewResult, setReviewResult] = useState<Record<string, unknown> | null>(null)
  const [reviewError, setReviewError] = useState('')
  const [reviewing, setReviewing] = useState(false)

  useEffect(() => {
    setScope(session.beginScope())
  }, [session.selection?.epoch, session.selection?.taskId, session.beginScope])

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const result = await api.mappingContract()
        if (alive) setContract(result)
      } catch {
        /* 合同拉不到时表单不可用，下面会提示原因 */
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const fileOptions = useMemo(
    () => (session.isCurrent(scope) ? session.files : []).filter((file) => file.suffix === '.csv'
      || file.suffix === '.tsv' || file.suffix === '.xlsx'),
    [session.files, scope, session],
  )

  useEffect(() => {
    setDescribed(null)
    setSaveResult(null)
    setPreviewResult(null)
    setReviewResult(null)
    setRows([])
  }, [fileId])

  /** 读一次上传文件：真实列、表头单位、样本、不齐列/重复表头——不猜任何东西。 */
  const describe = useCallback(async () => {
    if (!fileId || !scope) return
    setDescribeError('')
    setDescribed(null)
    setSaveResult(null)
    setPreviewResult(null)
    setReviewResult(null)
    try {
      const result = await api.describeInput(scope.projectId, scope.taskId, fileId)
      if (!session.isCurrent(scope)) return
      setDescribed(result)
      // 用服务端建议预填（只是建议：单位/目标都由人最后确认，rows 全部可改）
      const seed: MappingRow[] = result.suggestions.map((item: InputColumn) => ({
        source: item.source,
        target: item.suggested_target ?? '',
        unit: item.header_unit ?? '',
        required: item.suggested_target === 'ys_mpa' || item.suggested_target === 'uts_mpa'
          || item.suggested_target === 'el_pct' || item.suggested_target === 'specimen_id',
      }))
      setRows(seed)
      const base = fileId.replace(/\.[^.]+$/, '').replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '')
      setProfileId((previous) => previous || `${base || 'profile'}-v1`)
    } catch (error) {
      if (session.isCurrent(scope)) {
        setDescribeError(error instanceof Error ? error.message : String(error))
      }
    }
  }, [fileId, scope, session])

  function targetOptions(): string[] {
    if (!contract) return []
    return contract.allowed_targets[domain] ?? []
  }

  function unitOptions(target: string): string[] {
    if (!contract) return []
    return contract.allowed_units[target] ?? []
  }

  function buildPayload(): Record<string, unknown> {
    const columns = rows
      .filter((row) => row.target !== '')
      .map((row) => ({
        source: row.source,
        target: row.target,
        dtype: contract?.text_targets.includes(row.target) ? 'text' : 'number',
        unit: contract?.text_targets.includes(row.target) ? '' : row.unit,
        target_unit: contract?.targets[row.target] ?? '',
        required: row.required,
      }))
    return {
      profile_id: profileId.trim(),
      input_file: fileId,
      domain,
      layout,
      header_row: Number(headerRow) || 1,
      columns,
    }
  }

  async function save() {
    if (!scope) return
    setSaving(true)
    setSaveError('')
    setSaveResult(null)
    setPreviewResult(null)
    try {
      const result = await api.saveMapping(scope.projectId, scope.taskId, buildPayload())
      if (!session.isCurrent(scope)) return
      setSaveResult(result)
      if (result.ok) {
        await session.reloadProfiles()
        await session.reloadReviews()
      }
    } catch (error) {
      if (session.isCurrent(scope)) setSaveError(error instanceof Error ? error.message : String(error))
    } finally {
      setSaving(false)
    }
  }

  async function preview(profile: CandidateProfile) {
    if (!scope) return
    setPreviewResult(null)
    try {
      const result = await api.previewProfile(scope.projectId, scope.taskId, profile.profile_id)
      if (!session.isCurrent(scope)) return
      setPreviewResult(result)
    } catch (error) {
      setPreviewResult({ ok: false, problem: error instanceof Error ? error.message : String(error) })
    }
  }

  async function review(decision: 'approve' | 'reject') {
    if (!scope) return
    setReviewing(true)
    setReviewError('')
    setReviewResult(null)
    try {
      const result = await api.review(scope.projectId, scope.taskId, {
        profile_id: activeProfile?.profile_id ?? profileId.trim(),
        decision,
        reviewer: reviewer.trim(),
        note: note.trim(),
      }, synthetic)
      if (!session.isCurrent(scope)) return
      setReviewResult(result)
      await session.reloadProfiles()
      await session.reloadReviews()
    } catch (error) {
      if (session.isCurrent(scope)) setReviewError(error instanceof Error ? error.message : String(error))
    } finally {
      setReviewing(false)
    }
  }

  const activeProfile: CandidateProfile | undefined = useMemo(() => {
    if (session.profiles.length === 0) return undefined
    return session.profiles.find((item) => item.profile_id === profileId.trim())
      ?? session.profiles[0]
  }, [session.profiles, profileId])

  const canReview = session.sessionInfo?.actor_kind !== 'ai-assistant'
  const needsHuman = saveResult && Array.isArray((saveResult as { needs_human?: unknown }).needs_human)
    ? ((saveResult as { needs_human?: string[] }).needs_human ?? [])
    : []

  if (!session.selection || !session.taskId) {
    return (
      <div className="page">
        <div className="page-head">
          <h2>数据处理</h2>
        </div>
        <EmptyState title="未选择任务" hint="请先到“项目”页选择项目与任务；上传的输入、映射与人审都归属当前任务。" />
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-head">
        <h2>数据处理</h2>
        <p className="muted">
          上传 → 网页映射/单位 → SteelData 预览 → 具名人工确认 → 按确认运行。映射与确认都落在本任务
          服务端目录（<code>profiles/</code>、<code>approvals/</code>），上传内容**不能**冒充人审授权；
          未知单位、缺单位、必需字段缺失一律停在 <code>needs_human</code>，不猜、不把缺值补零。
        </p>
      </div>

      <section className="panel">
        <h3>1 · 选择本次上传的输入文件</h3>
        {fileOptions.length === 0 && (
          <EmptyState
            title="本任务还没有可映射的输入"
            hint="先在“资料”页上传 CSV / TSV / XLSX；其它类型只能预览/下载，不能进入映射与运行。"
          />
        )}
        {fileOptions.length > 0 && (
          <div className="form-row">
            <label className="field">
              <span className="field-label">输入文件（仅本任务）</span>
              <select value={fileId} onChange={(event) => setFileId(event.target.value)}>
                <option value="">（选择文件）</option>
                {fileOptions.map((file) => (
                  <option key={file.file_id} value={file.file_id}>
                    {file.name} · {formatBytes(file.size)}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="primary" onClick={() => void describe()} disabled={!fileId}>
              读取列与单位
            </button>
          </div>
        )}
        {describeError && <p className="warn-text">{describeError}</p>}
        {described && !described.supported && (
          <p className="warn-text">
            该文件不能用于映射：{described.problem}。{described.note}
          </p>
        )}
        {described?.supported && (
          <>
            <p className="muted small">
              {described.columns.length} 列 · {described.records} 条记录 · 输入 SHA-256{' '}
              <code className="hash">{described.input_sha256.slice(0, 16)}…</code>
              {described.has_formulas ? ' · 含公式（SteelData 运行会要求"仅值"导出）' : ''}
            </p>
            {described.ragged_rows && described.ragged_rows.length > 0 && (
              <p className="warn-text">
                有 {described.ragged_rows.length} 行列数与表头不一致：需先修数据再映射，本页不会替你补齐。
              </p>
            )}
            {described.duplicate_headers && described.duplicate_headers.length > 0 && (
              <p className="warn-text">重复表头：{described.duplicate_headers.join('、')}</p>
            )}
          </>
        )}
      </section>

      {described?.supported && (
        <>
          <section className="panel">
            <h3>2 · 映射与单位（只选已支持的字段/单位）</h3>
            {!contract && <EmptyState title="映射合同未就绪" hint="未能从服务端拿到 SteelData 映射合同，请刷新页面重试。" />}
            {contract && (
              <>
                <div className="form-row">
                  <label className="field">
                    <span className="field-label">领域</span>
                    <select value={domain} onChange={(event) => setDomain(event.target.value)}>
                      {contract.domains.map((item) => (
                        <option key={item} value={item}>
                          {DOMAIN_LABEL[item] ?? item}
                          {contract.required_targets[item] ? `（必需：${contract.required_targets[item].join('/')}）` : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span className="field-label">版式</span>
                    <select value={layout} onChange={(event) => setLayout(event.target.value)}>
                      {contract.layouts.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span className="field-label">表头行</span>
                    <input value={headerRow} onChange={(event) => setHeaderRow(event.target.value)} />
                  </label>
                  <label className="field">
                    <span className="field-label">候选 profile 标识<em className="required">*</em></span>
                    <input value={profileId} onChange={(event) => setProfileId(event.target.value)}
                           placeholder="t001-tensile-v1" />
                  </label>
                </div>

                {domain === 'composition' && (
                  <p className="warn-text">
                    composition 是堆叠报表合同（block/element/unit/basis 标签 + row_roles），形态与前两列差异大；
                    本页不硬塞一个简化表单——请用原 CLI <code>steeldata profile</code> 生成后放到本任务输入目录导入，
                    或先用 tensile / tensile_curve。
                  </p>
                )}

                {domain !== 'composition' && (
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>原列</th><th>样本</th><th>目标字段</th><th>单位（显式）</th><th>必需</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row, index) => {
                          const suggestion = described.suggestions.find((item) => item.source === row.source)
                          const conflict = Boolean(
                            row.target && row.unit
                              && !(contract.allowed_units[row.target] ?? []).includes(row.unit),
                          )
                          const textTarget = contract.text_targets.includes(row.target)
                          return (
                            <tr key={row.source}>
                              <td><code>{row.source}</code>
                                {suggestion?.header_unit && (
                                  <span className="muted small">（表头单位 {suggestion.header_unit}）</span>
                                )}
                              </td>
                              <td className="muted small">{(suggestion?.samples ?? []).slice(0, 2).join(' / ') || '—'}</td>
                              <td>
                                <select
                                  value={row.target}
                                  onChange={(event) => {
                                    const next = [...rows]
                                    next[index] = { ...row, target: event.target.value, unit: '' }
                                    setRows(next)
                                  }}
                                >
                                  <option value="">（不映射）</option>
                                  {targetOptions().map((target) => (
                                    <option key={target} value={target}>{target}</option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                {textTarget || !row.target
                                  ? <span className="muted small">—</span>
                                  : (
                                    <select
                                      value={row.unit}
                                      onChange={(event) => {
                                        const next = [...rows]
                                        next[index] = { ...row, unit: event.target.value }
                                        setRows(next)
                                      }}
                                    >
                                      <option value="">（未知→需人确认）</option>
                                      {unitOptions(row.target).map((unit) => (
                                        <option key={unit} value={unit}>{unit}</option>
                                      ))}
                                    </select>
                                  )}
                                {conflict && (
                                  <span className="warn-text small">
                                    该单位不属于 {row.target}（可用 {unitOptions(row.target).join('/')}）
                                  </span>
                                )}
                              </td>
                              <td>
                                <input
                                  type="checkbox"
                                  checked={row.required}
                                  onChange={(event) => {
                                    const next = [...rows]
                                    next[index] = { ...row, required: event.target.checked }
                                    setRows(next)
                                  }}
                                />
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="cap-actions">
                  <button type="button" className="primary" onClick={() => void save()} disabled={saving || domain === 'composition'}>
                    {saving ? '保存中…' : '保存候选映射'}
                  </button>
                  <span className="muted small">
                    单位留空＝不知道：会停在 needs_human，不会替你猜，也不会把缺值改成 0。
                  </span>
                </div>
                {saveError && <p className="warn-text">{saveError}</p>}
              </>
            )}
          </section>

          {(saveResult || needsHuman.length > 0) && (
            <section className="panel">
              <h3>3 · 保存结果 / needs_human</h3>
              {needsHuman.length > 0 && (
                <>
                  <p className="warn-text">需要人工处理（未保存）：</p>
                  <ul className="artifact-list">
                    {needsHuman.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </>
              )}
              {saveResult?.ok === true && (
                <>
                  <p className="cap-message">
                    已保存候选 profile：<code>{String(saveResult.profile_id)}</code>；
                    SteelData 复核摘要 <code className="hash">{String(saveResult.profile_sha256).slice(0, 16)}…</code>
                    {Array.isArray(saveResult.invalidated_approvals) && (saveResult.invalidated_approvals as string[]).length > 0
                      && '（旧确认已失效并清除）'}
                  </p>
                  <pre className="code-block small">
                    {JSON.stringify(saveResult.preview ?? {}, null, 2)}
                  </pre>
                </>
              )}
            </section>
          )}

          <section className="panel">
            <h3>4 · 具名人工确认（受限能力）</h3>
            {!canReview && (
              <p className="warn-text">
                当前是本地 AI 会话：可以读、可以建议、可以在人确认后执行，但<strong>不能代人审</strong>。
                服务端会拒绝 AI 会话的确认请求，即使这里填了具名审批人。
              </p>
            )}
            {session.profiles.length === 0 && <EmptyState title="还没有候选映射" hint="先在上面保存一个候选映射。" />}
            {session.profiles.length > 0 && (
              <>
                <p className="muted small">
                  确认对象：<code>{activeProfile?.profile_id}</code>
                  {activeProfile?.approval_sha256
                    ? ' · 已有审批（profile_sha256 ' + activeProfile.approval_sha256.slice(0, 12) + '…）'
                    : ' · 尚未审批'}
                  {activeProfile?.meta?.input_file ? ` · 输入 ${activeProfile.meta.input_file}` : ''}
                </p>
                <div className="form-row">
                  <label className="field">
                    <span className="field-label">审批人（真实姓名）<em className="required">*</em></span>
                    <input value={reviewer} onChange={(event) => setReviewer(event.target.value)}
                           placeholder="不能填 system/agent/web 之类" />
                  </label>
                  <label className="field">
                    <span className="field-label">审批备注<em className="required">*</em></span>
                    <input value={note} onChange={(event) => setNote(event.target.value)}
                           placeholder="核对了哪份输入、单位与样列，依据是什么" />
                  </label>
                  <label className="field">
                    <span className="field-label">合成验收记录</span>
                    <select value={synthetic ? 'yes' : 'no'} onChange={(event) => setSynthetic(event.target.value === 'yes')}>
                      <option value="yes">是（本批隔离合成验收，记录标 synthetic）</option>
                      <option value="no">否（真实数据）</option>
                    </select>
                  </label>
                </div>
                <div className="cap-actions">
                  <button type="button" className="primary" disabled={!canReview || reviewing}
                          onClick={() => void review('approve')}>
                    同意并生成审批文件
                  </button>
                  <button type="button" className="chip" disabled={!canReview || reviewing}
                          onClick={() => void review('reject')}>
                    拒绝（并使旧确认失效）
                  </button>
                  <button type="button" className="chip" onClick={() => activeProfile && void preview(activeProfile)}>
                    用 SteelData 预览此映射
                  </button>
                </div>
                {reviewError && <p className="warn-text">{reviewError}</p>}
                {reviewResult && (
                  <p className={reviewResult.ok ? 'cap-message' : 'warn-text'}>
                    {String(reviewResult.message ?? reviewResult.problem ?? JSON.stringify(reviewResult))}
                  </p>
                )}
                {previewResult && (
                  <pre className="code-block small">{JSON.stringify(previewResult, null, 2)}</pre>
                )}
              </>
            )}
          </section>

          <section className="panel">
            <h3>本任务候选映射（{session.profiles.length}）</h3>
            {session.profiles.length === 0 && <EmptyState title="没有候选映射" hint="保存后在这里列出。" />}
            {session.profiles.map((profile) => (
              <div key={profile.profile_id} className="run-line">
                <code>{profile.profile_id}</code>
                <span className="muted small">
                  {profile.meta?.input_file} · 摘要 {String(profile.meta?.profile_sha256 ?? '').slice(0, 12)}…
                </span>
                {profile.approval_sha256
                  ? <span className="badge badge-ok">已确认</span>
                  : <span className="badge badge-warn">未确认</span>}
                <button type="button" className="chip" onClick={() => void preview(profile)}>预览</button>
                <button type="button" className="chip" onClick={() => setProfileId(profile.profile_id)}>设为确认对象</button>
              </div>
            ))}
          </section>

          <section className="panel">
            <h3>确认记录（{session.reviews.length}）</h3>
            {session.reviews.length === 0 && <EmptyState title="还没有确认记录" hint="同意/拒绝/导入审批都会登记在这里。" />}
            <ul className="artifact-list">
              {session.reviews.slice().reverse().map((entry: ReviewEntry) => (
                <li key={`${entry.review_id}-${entry.created}`}>
                  <code>{entry.kind}</code>
                  <span className="muted small">
                    {entry.decision ? `${entry.decision} · ` : ''}{entry.reviewer || '—'} · {entry.created}
                    {entry.synthetic ? ' · 合成验收' : ''}
                  </span>
                  <span className="muted small">{entry.note || entry.reason || ''}</span>
                  {entry.input_sha256 && <code className="hash">{entry.input_sha256.slice(0, 12)}…</code>}
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <h3>5 · 按确认运行（原 SteelData CLI）</h3>
            <p className="muted small">
              运行会再次复核审批：输入或映射变化后旧确认失效，输入文件必须来自本任务、审批文件必须落在本任务
              <code>approvals/</code>（网页人审生成）或 <code>inputs/</code>（导入的既有审批）。
            </p>
          </section>
        </>
      )}

      <GridLayout
        projectId={session.projectId}
        page={session.page}
        primaryLabel="数据处理能力（原 CLI）"
        secondaryLabel="运行结果"
        primary={
          <div className="cap-list">
            {caps.length === 0 && <EmptyState title="没有数据处理能力" hint="薄 API 未返回 data_processing 能力。" />}
            {caps.map((cap: Capability) => <ToolRunner key={cap.tool_id} capability={cap} />)}
          </div>
        }
        secondary={
          active
            ? <RunDetail run={active} />
            : <EmptyState title="还没有运行" hint="在上面完成人审后点“运行”，结果会出现在这里。" />
        }
      />
    </div>
  )
}
