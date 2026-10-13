/**
 * WO-31 §2 — 单一项目/任务会话上下文。
 *
 * 六个页面共享同一个 project_id / task_id / run_id；换项目或换任务时**先清空**
 * 上一条任务的文件、运行与选中产物，避免把旧结果或旧审批带到新项目上。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  api,
  type Artifact,
  type Capability,
  type FileEntry,
  type ProjectSummary,
  type RunRecord,
  type TaskContext,
} from '../api/client'

export type PageKey =
  | 'projects'
  | 'files'
  | 'data_processing'
  | 'tools'
  | 'artifacts'
  | 'work_log'

interface SessionValue {
  ready: boolean
  error: string
  workRoot: string
  researchAppUrl: string
  allowedOrigins: string[]
  capabilities: Capability[]
  projects: ProjectSummary[]
  projectId: string
  taskId: string
  page: PageKey
  files: FileEntry[]
  context: TaskContext | null
  runs: RunRecord[]
  artifacts: Artifact[]
  activeRunId: string
  busy: string
  setPage: (page: PageKey) => void
  selectProject: (projectId: string) => void
  selectTask: (taskId: string) => void
  setActiveRun: (runId: string) => void
  refreshAll: () => Promise<void>
  refreshTask: () => Promise<void>
  reloadRuns: () => Promise<void>
  reloadArtifacts: () => Promise<void>
  createTask: (taskId: string, title: string, note: string) => Promise<void>
  runTool: (toolId: string, params: Record<string, unknown>) => Promise<RunRecord>
  uploadFile: (file: File) => Promise<void>
  deleteFile: (fileId: string) => Promise<void>
  saveHandoff: (markdown: string) => Promise<void>
  setError: (message: string) => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [workRoot, setWorkRoot] = useState('')
  const [researchAppUrl, setResearchAppUrl] = useState('')
  const [allowedOrigins, setAllowedOrigins] = useState<string[]>([])
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [projectId, setProjectId] = useState('')
  const [taskId, setTaskId] = useState('')
  const [page, setPage] = useState<PageKey>('projects')
  const [files, setFiles] = useState<FileEntry[]>([])
  const [context, setContext] = useState<TaskContext | null>(null)
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [activeRunId, setActiveRunId] = useState('')
  const [busy, setBusy] = useState('')
  const selection = useRef({ projectId: '', taskId: '' })

  const clearTaskScoped = useCallback(() => {
    setFiles([])
    setContext(null)
    setRuns([])
    setArtifacts([])
    setActiveRunId('')
  }, [])

  const reloadRuns = useCallback(async () => {
    const current = selection.current
    if (!current.projectId || !current.taskId) {
      setRuns([])
      return
    }
    const result = await api.runs(current.projectId, current.taskId)
    if (selection.current.taskId !== current.taskId) return
    setRuns(result.runs)
  }, [])

  const reloadArtifacts = useCallback(async () => {
    const current = selection.current
    if (!current.projectId || !current.taskId) {
      setArtifacts([])
      return
    }
    const result = await api.artifacts(current.projectId, current.taskId)
    if (selection.current.taskId !== current.taskId) return
    setArtifacts(result.artifacts)
  }, [])

  const refreshTask = useCallback(async () => {
    const current = selection.current
    if (!current.projectId || !current.taskId) {
      clearTaskScoped()
      return
    }
    const [fileList, ctx, runList, artifactList] = await Promise.all([
      api.files(current.projectId, current.taskId),
      api.context(current.projectId, current.taskId),
      api.runs(current.projectId, current.taskId),
      api.artifacts(current.projectId, current.taskId),
    ])
    if (selection.current.taskId !== current.taskId) return
    setFiles(fileList.files)
    setContext(ctx)
    setRuns(runList.runs)
    setArtifacts(artifactList.artifacts)
  }, [clearTaskScoped])

  const refreshAll = useCallback(async () => {
    try {
      const [health, caps, proj] = await Promise.all([
        api.health(),
        api.capabilities(),
        api.projects(),
      ])
      setWorkRoot(health.work_root)
      setResearchAppUrl(health.research_app_url)
      setAllowedOrigins(health.allowed_origins)
      setCapabilities(caps.tools)
      setProjects(proj.projects)
      const currentProject = proj.projects.find((item) => item.project_id === selection.current.projectId)
        ?? proj.projects.find((item) => item.synthetic)
        ?? proj.projects[0]
      if (currentProject) {
        selection.current.projectId = currentProject.project_id
        setProjectId(currentProject.project_id)
        const firstTask = currentProject.tasks[0]
        if (firstTask) {
          selection.current.taskId = firstTask.task_id
          setTaskId(firstTask.task_id)
        }
      }
      await refreshTask()
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setReady(true)
    }
  }, [refreshTask])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  // 运行中的任务轮询，直到全部进入终态；刷新页面后按磁盘状态继续。
  useEffect(() => {
    const pending = runs.filter((run) => run.status === 'queued' || run.status === 'running')
    if (pending.length === 0) return
    const timer = window.setTimeout(async () => {
      const updates = await Promise.all(pending.map((run) => api.run(run.run_id).catch(() => null)))
      setRuns((previous) => previous.map((run) => {
        const update = updates.find((item) => item?.run.run_id === run.run_id)
        return update ? update.run : run
      }))
      await reloadArtifacts()
    }, 1200)
    return () => window.clearTimeout(timer)
  }, [runs, reloadArtifacts])

  const selectProject = useCallback((nextProjectId: string) => {
    const project = projects.find((item) => item.project_id === nextProjectId)
    selection.current = { projectId: nextProjectId, taskId: '' }
    setProjectId(nextProjectId)
    setTaskId('')
    clearTaskScoped()
    const firstTask = project?.tasks[0]
    if (firstTask) {
      selection.current.taskId = firstTask.task_id
      setTaskId(firstTask.task_id)
      void refreshTask()
    }
  }, [projects, clearTaskScoped, refreshTask])

  const selectTask = useCallback((nextTaskId: string) => {
    selection.current.taskId = nextTaskId
    setTaskId(nextTaskId)
    clearTaskScoped()
    void refreshTask()
  }, [clearTaskScoped, refreshTask])

  const createTask = useCallback(async (newTaskId: string, title: string, note: string) => {
    setBusy('create-task')
    try {
      await api.createTask(selection.current.projectId, newTaskId, title, note)
      const result = await api.projects()
      setProjects(result.projects)
      selection.current.taskId = newTaskId
      setTaskId(newTaskId)
      clearTaskScoped()
      await refreshTask()
    } finally {
      setBusy('')
    }
  }, [clearTaskScoped, refreshTask])

  const runTool = useCallback(async (toolId: string, params: Record<string, unknown>) => {
    setBusy(toolId)
    try {
      const result = await api.createRun(selection.current.projectId, selection.current.taskId, toolId, params)
      setRuns((previous) => [result.run, ...previous])
      setActiveRunId(result.run.run_id)
      if (result.run.status !== 'queued') {
        setError(result.run.error || `${result.run.tool_label} 不可用`)
      }
      return result.run
    } finally {
      setBusy('')
    }
  }, [])

  const uploadFile = useCallback(async (file: File) => {
    setBusy('upload')
    try {
      await api.upload(selection.current.projectId, selection.current.taskId, file)
      await refreshTask()
    } finally {
      setBusy('')
    }
  }, [refreshTask])

  const deleteFile = useCallback(async (fileId: string) => {
    setBusy('delete-file')
    try {
      await api.deleteFile(selection.current.projectId, selection.current.taskId, fileId)
      await refreshTask()
    } finally {
      setBusy('')
    }
  }, [refreshTask])

  const saveHandoff = useCallback(async (markdown: string) => {
    setBusy('handoff')
    try {
      await api.saveHandoff(selection.current.projectId, selection.current.taskId, markdown)
      await refreshTask()
    } finally {
      setBusy('')
    }
  }, [refreshTask])

  const value = useMemo<SessionValue>(() => ({
    ready,
    error,
    workRoot,
    researchAppUrl,
    allowedOrigins,
    capabilities,
    projects,
    projectId,
    taskId,
    page,
    files,
    context,
    runs,
    artifacts,
    activeRunId,
    busy,
    setPage,
    selectProject,
    selectTask,
    setActiveRun: setActiveRunId,
    refreshAll,
    refreshTask,
    reloadRuns,
    reloadArtifacts,
    createTask,
    runTool,
    uploadFile,
    deleteFile,
    saveHandoff,
    setError,
  }), [
    ready, error, workRoot, researchAppUrl, allowedOrigins, capabilities, projects, projectId, taskId, page, files, context,
    runs, artifacts, activeRunId, busy, selectProject, selectTask, refreshAll, refreshTask,
    reloadRuns, reloadArtifacts, createTask, runTool, uploadFile, deleteFile, saveHandoff,
  ])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession 必须在 SessionProvider 内使用')
  return value
}
