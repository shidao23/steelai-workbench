/**
 * WO-31 §3 — 薄 API 的类型化客户端。
 *
 * 这里只提交**标识**（project_id / task_id / file_id / run_id）与固定 schema 的参数；
 * 路径、解释器、URL 一律由服务端解析，前端不构造任何磁盘路径。
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
}

export interface FileEntry {
  file_id: string
  name: string
  size: number
  suffix: string
  modified: string
  previewable: boolean
}

export type Preview =
  | { kind: 'table'; file_id: string; size: number; delimiter: string; columns: string[]; rows: string[][]; total_lines: number; truncated: boolean }
  | { kind: 'json'; file_id: string; size: number; json_head: unknown }
  | { kind: 'text'; file_id: string; size: number; text: string; truncated: boolean }
  | { kind: 'image'; file_id: string; size: number; image: { format: string; width: number | null; height: number | null }; note: string }
  | { kind: 'workbook'; file_id: string; size: number; sheets: string[]; sheet: string; columns: string[]; rows: string[][] }
  | { kind: 'binary'; file_id: string; size: number; note: string }

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
      else if (body && typeof body.detail === 'object') detail = JSON.stringify(body.detail)
    } catch {
      /* keep the status line */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<{
    status: string
    frontend_built: boolean
    work_root: string
    research_app_url: string
    allowed_origins: string[]
  }>('/api/health'),

  capabilities: () => request<{ tools: Capability[] }>('/api/capabilities'),

  projects: () => request<{ projects: ProjectSummary[]; notes: string[] }>('/api/projects'),

  tasks: (projectId: string) =>
    request<{ tasks: TaskSummary[] }>(`/api/projects/${projectId}/tasks`),

  createTask: (projectId: string, taskId: string, title: string, note: string) =>
    request<{ task: TaskSummary }>(`/api/projects/${projectId}/tasks`, {
      method: 'POST',
      body: JSON.stringify({ task_id: taskId, title, note }),
    }),

  context: (projectId: string, taskId: string) =>
    request<TaskContext>(`/api/projects/${projectId}/tasks/${taskId}/context`),

  files: (projectId: string, taskId: string) =>
    request<{ files: FileEntry[] }>(`/api/projects/${projectId}/tasks/${taskId}/files`),

  preview: (projectId: string, taskId: string, fileId: string) =>
    request<Preview>(
      `/api/projects/${projectId}/tasks/${taskId}/preview?file_id=${encodeURIComponent(fileId)}`,
    ),

  upload: async (projectId: string, taskId: string, file: File) => {
    const form = new FormData()
    form.append('file', file, file.name)
    const response = await fetch(`/api/projects/${projectId}/tasks/${taskId}/upload`, {
      method: 'POST',
      body: form,
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail ?? `${response.status}`)
    }
    return (await response.json()) as { uploaded: { file_id: string; size: number } }
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

  runs: (projectId: string, taskId: string) =>
    request<{ runs: RunRecord[] }>(`/api/projects/${projectId}/tasks/${taskId}/runs`),

  run: (runId: string) => request<{ run: RunRecord }>(`/api/runs/${runId}`),

  artifacts: (projectId: string, taskId: string) =>
    request<{ artifacts: Artifact[] }>(`/api/projects/${projectId}/tasks/${taskId}/artifacts`),

  saveHandoff: (projectId: string, taskId: string, markdown: string) =>
    request<{ written: boolean }>(`/api/projects/${projectId}/tasks/${taskId}/handoff`, {
      method: 'POST',
      body: JSON.stringify({ markdown }),
    }),

  promote: (projectId: string, taskId: string, runId: string, reviewer: string) =>
    request<unknown>(`/api/projects/${projectId}/tasks/${taskId}/promote`, {
      method: 'POST',
      body: JSON.stringify({ run_id: runId, reviewer }),
    }),
}

export function artifactUrl(runId: string, rel: string): string {
  const encoded = rel.split('/').map(encodeURIComponent).join('/')
  return `/api/runs/${runId}/artifacts/${encoded}`
}
