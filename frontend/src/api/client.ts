/**
 * WO-31 §3 / WO-32 §1-§3 — 薄 API 的类型化客户端。
 *
 * 这里只提交**标识**（project_id / task_id / file_id / run_id）与固定 schema 的参数；
 * 路径、解释器、URL 一律由服务端解析，前端不构造任何磁盘路径。
 *
 * WO-32 新增：
 * * **本地会话令牌**：首次请求前申请；服务端进程在内存里持有它，重启后失效，
 *   收到 401 会自动重申请一次再重试（不弹 SSO，也没有常驻认证服务）。
 * * **AbortSignal**：换任务/项目/卸载时取消在途请求，迟到的响应由调用方
 *   按 epoch 快照丢弃。
 * * 映射/人审/运行前复核等 §1 端点。
 */

export interface ProjectSummary {
  project_id: string
  directory_name: string
  short_name: string
  status: string
  source: string
  synthetic: boolean
  root_exists: boolean
  task_count: number
  tasks: TaskSummary[]
}

export interface TaskSummary {
  project_id: string
  task_id: string
  title: string
  created_at: string
  run_count: number
  file_count: number
  profile_count?: number
  approval_count?: number
}

export interface FileEntry {
  file_id: string
  name: string
  size: number
  sha256?: string
  suffix: string
  modified: string
  previewable: boolean
}

export interface PreviewCommon {
  file_id: string
  size: number
  records?: number
  total_lines?: number
  physical_lines?: number
  truncated?: boolean
  delimiter?: string
  delimiter_source?: string
  sheet?: string
  sheets?: string[]
  has_formulas?: boolean
  ragged_rows?: number[]
  duplicate_headers?: string[]
  empty_headers?: string[]
  notes?: string[]
  encoding?: string
  problem?: string
  note?: string
}

export type Preview =
  | (PreviewCommon & { kind: 'table'; columns: string[]; rows: string[][] })
  | (PreviewCommon & { kind: 'json'; json_head: unknown })
  | (PreviewCommon & { kind: 'text'; text: string })
  | (PreviewCommon & { kind: 'image'; image: { format: string; width: number | null; height: number | null } })
  | (PreviewCommon & { kind: 'workbook'; columns: string[]; rows: string[][] })
  | (PreviewCommon & { kind: 'binary' })
  | (PreviewCommon & { kind: 'error' })

export interface CapabilityField {
  name: string
  kind: 'file' | 'text' | 'number' | 'select' | 'points' | 'box' | 'list'
  label: string
  required: boolean
  help: string
  default: string | number | null
  options: string[]
  suffix: string
}

export interface Capability {
  tool_id: string
  page: string
  label: string
  description: string
  contract: string
  fields: CapabilityField[]
  outputs: string[]
  available: boolean
  reason: string
}

export interface Artifact {
  name: string
  rel: string
  size: number
  sha256: string
  run_id?: string
  tool_id?: string
  tool_label?: string
  status?: string
  created?: string
}

export interface RunRecord {
  run_id: string
  project_id: string
  task_id: string
  tool_id: string
  tool_label: string
  params: Record<string, unknown>
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'timeout' | 'blocked'
  created: string
  started: string
  finished: string
  exit_code: number | null
  output_dir: string
  artifacts: Artifact[]
  result_dirs: string[]
  stdout_tail: string
  stderr_tail: string
  error: string
  actor: string
  session_id?: string
  actor_kind?: string
  approval_origin?: string
  approval_file?: string
  approval_profile_id?: string
  approval_profile_sha256?: string
  approval_input_sha256?: string
  approval_reviewer?: string
  approval_synthetic?: boolean
  duration_sec: number | null
}

export interface TaskContext {
  project_id: string
  task_id: string
  root: string
  task_markdown: string
  handoff_markdown: string
  inputs: string[]
}

export interface MappingContract {
  domains: string[]
  layouts: string[]
  allowed_targets: Record<string, string[]>
  text_targets: string[]
  targets: Record<string, string>
  allowed_units: Record<string, string[]>
  required_targets: Record<string, string[]>
  supported_formats: string[]
}

export interface SessionInfo {
  session_id: string
  client: 'browser' | 'ai'
  actor_kind: string
  capabilities: string[]
  issued_at: string
  expires_at: string
  origin: string
}

export interface InputColumn {
  index: number
  source: string
  suggested_target: string | null
  header_unit: string | null
  unit_conflict: boolean
  samples: string[]
  dtype_guess: string
}

export interface DescribeInput {
  file_id: string
  supported: boolean
  problem: string
  note: string
  columns: string[]
  records: number
  input_sha256: string
  suggestions: InputColumn[]
  ragged_rows?: number[]
  duplicate_headers?: string[]
  empty_headers?: string[]
  notes?: string[]
  has_formulas?: boolean
  preview_rows?: string[][]
}

export interface ProfileMeta {
  profile_id: string
  project_id: string
  task_id: string
  input_file: string
  input_sha256: string
  profile_sha256: string
  domain: string
  layout: string
  created: string
  previous_profile_sha256?: string | null
}

export interface CandidateProfile {
  profile_id: string
  profile: Record<string, unknown>
  meta: ProfileMeta
  approval_sha256: string
}

export interface MappingDraftColumn {
  source: string
  target: string
  dtype: string
  unit: string
  target_unit: string
  required: boolean
}

export interface ReviewEntry {
  review_id: string
  kind: string
  decision?: string
  profile_id: string
  reviewer: string
  note: string
  synthetic: boolean
  created: string
  input_sha256?: string
  approval_file?: string
  approval_sha256?: string
  reason?: string
  input_file?: string
}

export interface ResearchUrl {
  url: string
  base_url: string
  project_id: string
  task_id: string
  task_root: string
}

// --------------------------------------------------------------------------- #
// 会话令牌：进程内持有 + 401 自动重申请（服务端令牌本就只活在进程内存里）
// --------------------------------------------------------------------------- #

let token = ''

export function currentToken(): string {
  return token
}

export function setSessionToken(next: string): void {
  token = next
}

async function ensureSession(): Promise<string> {
  if (token) return token
  const response = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client: 'browser' }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? '无法申请本地会话')
  }
  const payload = (await response.json()) as { token: string }
  token = payload.token
  return token
}

class Unauthorized extends Error {}

async function requestRaw<T>(path: string, init?: RequestInit, allowRetry = true): Promise<{ status: number; body: T; detail: string }> {
  const bearer = await ensureSession()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (bearer) headers.Authorization = `Bearer ${bearer}`
  if (init?.headers) Object.assign(headers, init.headers as Record<string, string>)
  const response = await fetch(path, { ...init, headers, signal: init?.signal ?? undefined })
  if (response.status === 401) {
    // 服务端重启过（令牌只存在进程内存）：重申请一次再重试，之后仍然失败就如实报错。
    if (allowRetry && token) {
      token = ''
      return requestRaw<T>(path, init, false)
    }
    throw new Unauthorized('本地会话已失效，页面会自动重新申请；若持续出现请刷新页面')
  }
  let detail = `${response.status} ${response.statusText}`
  let parsed: unknown = null
  try {
    parsed = await response.json()
  } catch {
    /* 非 JSON 响应 */
  }
  if (parsed && typeof parsed === 'object' && 'detail' in (parsed as Record<string, unknown>)) {
    const value = (parsed as Record<string, unknown>).detail
    detail = typeof value === 'string' ? value : JSON.stringify(value)
  }
  return { status: response.status, body: (parsed ?? {}) as T, detail }
}

async function request<T>(path: string, init?: RequestInit, allowRetry = true): Promise<T> {
  const { status, body, detail } = await requestRaw<T>(path, init, allowRetry)
  if (!(status >= 200 && status < 300)) throw new Error(detail)
  return body
}

export const api = {
  session: () => request<{ session: SessionInfo }>('/api/session'),

  mappingContract: () => request<MappingContract>('/api/mapping-contract'),

  health: () => request<{
    status: string
    frontend_built: boolean
    work_root: string
    research_app_url: string
    allowed_origins: string[]
  }>('/api/health'),

  capabilities: () => request<{ tools: Capability[] }>('/api/capabilities'),

  projects: (signal?: AbortSignal) =>
    request<{ projects: ProjectSummary[]; notes: string[] }>('/api/projects', { signal }),

  tasks: (projectId: string, signal?: AbortSignal) =>
    request<{ tasks: TaskSummary[] }>(`/api/projects/${projectId}/tasks`, { signal }),

  createTask: (projectId: string, taskId: string, title: string, note: string) =>
    request<{ task: TaskSummary }>(`/api/projects/${projectId}/tasks`, {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, title, note }),
    }),

  context: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<TaskContext>(`/api/projects/${projectId}/tasks/${taskId}/context`, { signal }),

  files: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<{ files: FileEntry[] }>(`/api/projects/${projectId}/tasks/${taskId}/files`, { signal }),

  preview: (projectId: string, taskId: string, fileId: string, signal?: AbortSignal) =>
    request<Preview>(
      `/api/projects/${projectId}/tasks/${taskId}/preview?file_id=${encodeURIComponent(fileId)}`,
      { signal },
    ),

  upload: async (projectId: string, taskId: string, file: File) => {
    const bearer = await ensureSession()
    const form = new FormData()
    form.append('file', file, file.name)
    const response = await fetch(`/api/projects/${projectId}/tasks/${taskId}/upload`, {
      method: 'POST',
      headers: bearer ? { Authorization: `Bearer ${bearer}` } : undefined,
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail ?? `${response.status}`)
    }
    return (await response.json()) as { uploaded: { file_id: string; size: number; sha256: string } }
  },

  deleteFile: (projectId: string, taskId: string, fileId: string) =>
    request<{ deleted: string }>(
      `/api/projects/${projectId}/tasks/${taskId}/files/${encodeURIComponent(fileId)}`,
      { method: 'DELETE' },
    ),

  createRun: (projectId: string, taskId: string, toolId: string, params: Record<string, unknown>) =>
    request<{ run: RunRecord }>(`/api/projects/${projectId}/tasks/${taskId}/runs`, {
      method: 'POST',
      body: JSON.stringify({ tool_id: toolId, params }),
    }),

  runs: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<{ runs: RunRecord[] }>(`/api/projects/${projectId}/tasks/${taskId}/runs`, { signal }),

  run: (runId: string, signal?: AbortSignal) =>
    request<{ run: RunRecord }>(`/api/runs/${runId}`, { signal }),

  artifacts: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<{ artifacts: Artifact[] }>(
      `/api/projects/${projectId}/tasks/${taskId}/artifacts`,
      { signal },
    ),

  saveHandoff: (projectId: string, taskId: string, markdown: string) =>
    request<{ written: boolean }>(`/api/projects/${projectId}/tasks/${taskId}/handoff`, {
      method: 'POST',
      body: JSON.stringify({ markdown }),
    }),

  promote: (projectId: string, taskId: string, runId: string, reviewer: string) =>
    requestRaw<Record<string, unknown>>(
      `/api/projects/${projectId}/tasks/${taskId}/promote`,
      {
        method: 'POST',
        body: JSON.stringify({ run_id: runId, reviewer }),
      },
    ).then((result) => ({
      status: result.status,
      pending: result.status === 501,
      detail: typeof result.detail === 'string' ? result.detail : '',
      body: result.body,
    })),

  // ---- WO-32 §1：网页映射 / 人审 / 运行前复核 ------------------------------ #

  describeInput: (projectId: string, taskId: string, fileId: string, signal?: AbortSignal) =>
    request<DescribeInput>(
      `/api/projects/${projectId}/tasks/${taskId}/describe-input?file_id=${encodeURIComponent(fileId)}`,
      { signal },
    ),

  profiles: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<{ profiles: CandidateProfile[] }>(
      `/api/projects/${projectId}/tasks/${taskId}/profiles`,
      { signal },
    ),

  saveMapping: (projectId: string, taskId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/projects/${projectId}/tasks/${taskId}/mapping`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  previewProfile: (projectId: string, taskId: string, profileId: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/api/projects/${projectId}/tasks/${taskId}/preview-profile?profile_id=${encodeURIComponent(profileId)}`,
      { signal },
    ),

  reviews: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<{ reviews: ReviewEntry[] }>(
      `/api/projects/${projectId}/tasks/${taskId}/reviews`,
      { signal },
    ),

  review: (projectId: string, taskId: string, payload: Record<string, unknown>, synthetic = false) =>
    request<Record<string, unknown>>(
      `/api/projects/${projectId}/tasks/${taskId}/review?synthetic=${synthetic ? 'true' : 'false'}`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  approval: (projectId: string, taskId: string, approvalFile: string, signal?: AbortSignal) =>
    request<Record<string, unknown>>(
      `/api/projects/${projectId}/tasks/${taskId}/approval?approval_file=${encodeURIComponent(approvalFile)}`,
      { signal },
    ),

  researchUrl: (projectId: string, taskId: string, signal?: AbortSignal) =>
    request<ResearchUrl>(`/api/projects/${projectId}/tasks/${taskId}/research-url`, { signal }),
}

export function artifactUrl(runId: string, rel: string): string {
  const encoded = rel.split('/').map(encodeURIComponent).join('/')
  return `/api/runs/${runId}/artifacts/${encoded}`
}

/**
 * 产物下载/预览：带 Authorization 的 fetch（`<img src>`/`<a href>` 不能带请求头，
 * 所以这里取 blob 再生成对象 URL；token 绝不进 URL）。
 */
const blobUrlCache = new Map<string, string>()

export async function artifactBlobUrl(runId: string, rel: string, revoke = false): Promise<string> {
  const key = `${runId}:${rel}`
  if (revoke) {
    const existing = blobUrlCache.get(key)
    if (existing) {
      URL.revokeObjectURL(existing)
      blobUrlCache.delete(key)
    }
    return ''
  }
  const cached = blobUrlCache.get(key)
  if (cached) return cached
  const bearer = await ensureSession()
  const response = await fetch(artifactUrl(runId, rel), {
    headers: bearer ? { Authorization: `Bearer ${bearer}` } : undefined,
  })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  const url = URL.createObjectURL(await response.blob())
  blobUrlCache.set(key, url)
  return url
}

export async function artifactText(runId: string, rel: string): Promise<string> {
  const bearer = await ensureSession()
  const response = await fetch(artifactUrl(runId, rel), {
    headers: bearer ? { Authorization: `Bearer ${bearer}` } : undefined,
  })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.text()
}
