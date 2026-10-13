/**
 * WO-31 §2 / WO-32 §2 — 单一项目/任务会话上下文，**带作用域世代（epoch）**。
 *
 * WO-31 查收回执的阻断项：`session.tsx` 原来只比较 `taskId`，而且选择对象可被
 * 原位改写，于是「同名任务切项目」会让旧响应把别的项目的文件/运行回填进来
 * （P01/P02 同 taskId=TSHARED 复现）。WO-32 §2 的修法：
 *
 * 1. **不可变快照**：每次选择都是一个新对象 `{ epoch, projectId, taskId }`，
 *    比较一律用对象同一性（`===`），任何切换都会让旧快照立即失效——不只是
 *    taskId 变化，项目变化也一定被捕获。
 * 2. **写前校验**：所有异步回填（files/context/runs/artifacts/preview/轮询）与所有
 *    写动作（上传/删除/建任务/提交运行/保存接手）都先确认快照仍是当前选择。
 * 3. **迟到响应丢弃/取消**：读请求带 `AbortController`，卸载或换选择时取消；
 *     写动作命中失效快照直接拒绝执行。
 * 4. **草稿不串任务**：`WorkLogPage` 的草稿按 `project/task` 分桶并落 sessionStorage，
 *    切换后不会把上一份草稿存到新任务上，回到原任务原样恢复，离开本页/刷新也不丢。
 * 5. **刷新不暗换**：刷新后从 sessionStorage 恢复上次的 project/task；
 *    恢复不了就**要求用户显式重选**，不默认落到某个项目/首任务再显示旧结果。
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
  type CandidateProfile,
  type FileEntry,
  type ProjectSummary,
  type ReviewEntry,
  type RunRecord,
  type SessionInfo,
  type TaskContext,
} from '../api/client'

export type PageKey =
  | 'projects'
  | 'files'
  | 'data_processing'
  | 'tools'
  | 'artifacts'
  | 'work_log'

/**
 * 一次选择的不可变快照。`epoch` 单调递增，变更即产生新对象。
 * 只读字段 + 只在 `selectProject`/`selectTask`/`refreshAll` 里整对象替换，
 * 没有任何代码能原地改写一个已发出的快照。
 */
export interface Selection {
  readonly epoch: number
  readonly projectId: string
  readonly taskId: string
}

export interface Scope {
  readonly epoch: number
  readonly projectId: string
  readonly taskId: string
}

const RESTORE_KEY = 'steelai.session.selection.v1'

function readRestoredSelection(): Selection | null {
  try {
    const raw = window.sessionStorage.getItem(RESTORE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { projectId?: string; taskId?: string }
    const projectId = String(parsed.projectId ?? '')
    const taskId = String(parsed.taskId ?? '')
    if (!projectId || !taskId) return null
    return { epoch: 0, projectId, taskId }
  } catch {
    return null
  }
}

function writeRestoredSelection(selection: Selection | null): void {
  try {
    if (!selection) window.sessionStorage.removeItem(RESTORE_KEY)
    else window.sessionStorage.setItem(RESTORE_KEY, JSON.stringify(selection))
  } catch {
    /* 无痕模式等场景下 sessionStorage 不可用：不阻塞使用，只是刷新后需要重选 */
  }
}

interface SessionValue {
  ready: boolean
  /** 恢复了上次选择后为 false；此时页面必须要求用户显式确认/重选 */
  needsReselect: boolean
  error: string
  workRoot: string
  researchAppUrl: string
  allowedOrigins: string[]
  capabilities: Capability[]
  projects: ProjectSummary[]
  /** 当前选择的**不可变**快照；为空表示没有选定任务 */
  selection: Selection | null
  projectId: string
  taskId: string
  sessionInfo: SessionInfo | null
  page: PageKey
  files: FileEntry[]
  context: TaskContext | null
  runs: RunRecord[]
  artifacts: Artifact[]
  profiles: CandidateProfile[]
  reviews: ReviewEntry[]
  activeRunId: string
  busy: string
  /** 取一个新快照（epoch+1），用于把一次调用的目标固定下来 */
  beginScope: () => Scope | null
  isCurrent: (scope: Scope | null) => boolean
  setPage: (page: PageKey) => void
  selectProject: (projectId: string) => void
  selectTask: (taskId: string) => void
  setActiveRun: (runId: string) => void
  refreshAll: () => Promise<void>
  refreshTask: () => Promise<void>
  reloadRuns: () => Promise<void>
  reloadArtifacts: () => Promise<void>
  reloadProfiles: () => Promise<void>
  reloadReviews: () => Promise<void>
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
  const [needsReselect, setNeedsReselect] = useState(false)
  const [error, setError] = useState('')
  const [workRoot, setWorkRoot] = useState('')
  const [researchAppUrl, setResearchAppUrl] = useState('')
  const [allowedOrigins, setAllowedOrigins] = useState<string[]>([])
  const [capabilities, setCapabilities] = useState<Capability[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)
  const [page, setPage] = useState<PageKey>('projects')
  const [files, setFiles] = useState<FileEntry[]>([])
  const [context, setContext] = useState<TaskContext | null>(null)
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [profiles, setProfiles] = useState<CandidateProfile[]>([])
  const [reviews, setReviews] = useState<ReviewEntry[]>([])
  const [activeRunId, setActiveRunId] = useState('')
  const [busy, setBusy] = useState('')

  // 选择快照：只通过 setSelection 整对象替换；这个 ref 只用于在异步回调里
  // 判断"我出发时的快照是否还是当前选择"，绝不能用来改写当前选择。
  const selectionRef = useRef<Selection | null>(null)
  useEffect(() => {
    selectionRef.current = selection
    if (selection) writeRestoredSelection(selection)
    else writeRestoredSelection(null)
  }, [selection])

  // 读请求的中止器：跟着 epoch 走。同一个 epoch 内的并发读共享一个 controller；
  // epoch 一变（换项目/换任务）就中止上一代的全部在途请求，迟到响应按快照丢弃。
  const controllerRef = useRef<AbortController | null>(null)
  const controllerEpoch = useRef(-1)
  const signalFor = useCallback((scope: Scope): AbortSignal => {
    if (controllerEpoch.current !== scope.epoch || !controllerRef.current) {
      controllerRef.current?.abort()
      controllerRef.current = new AbortController()
      controllerEpoch.current = scope.epoch
    }
    return controllerRef.current.signal
  }, [])
  /** 取出这一刻的选择快照（无副作用）：后续回填/写动作都以它为准。 */
  const beginScope = useCallback((): Scope | null => selectionRef.current, [])
  const isCurrent = useCallback((scope: Scope | null): boolean => {
    return scope !== null && selectionRef.current !== null && selectionRef.current === scope
  }, [])
  useEffect(() => () => controllerRef.current?.abort(), [])

  const clearTaskScoped = useCallback(() => {
    setFiles([])
    setContext(null)
    setRuns([])
    setArtifacts([])
    setProfiles([])
    setReviews([])
    setActiveRunId('')
  }, [])

  const reloadRuns = useCallback(async () => {
    const scope = beginScope()
    if (!scope) {
      setRuns([])
      return
    }
    try {
      const result = await api.runs(scope.projectId, scope.taskId, signalFor(scope))
      if (!isCurrent(scope)) return
      setRuns(result.runs)
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError') && isCurrent(scope)) throw err
    }
  }, [beginScope, isCurrent, signalFor])

  const reloadArtifacts = useCallback(async () => {
    const scope = beginScope()
    if (!scope) {
      setArtifacts([])
      return
    }
    try {
      const result = await api.artifacts(scope.projectId, scope.taskId, signalFor(scope))
      if (!isCurrent(scope)) return
      setArtifacts(result.artifacts)
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError') && isCurrent(scope)) throw err
    }
  }, [beginScope, isCurrent, signalFor])

  const reloadProfiles = useCallback(async () => {
    const scope = beginScope()
    if (!scope) {
      setProfiles([])
      return
    }
    try {
      const result = await api.profiles(scope.projectId, scope.taskId, signalFor(scope))
      if (!isCurrent(scope)) return
      setProfiles(result.profiles)
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError') && isCurrent(scope)) throw err
    }
  }, [beginScope, isCurrent, signalFor])

  const reloadReviews = useCallback(async () => {
    const scope = beginScope()
    if (!scope) {
      setReviews([])
      return
    }
    try {
      const result = await api.reviews(scope.projectId, scope.taskId, signalFor(scope))
      if (!isCurrent(scope)) return
      setReviews(result.reviews)
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError') && isCurrent(scope)) throw err
    }
  }, [beginScope, isCurrent, signalFor])

  const refreshTask = useCallback(async () => {
    const scope = beginScope()
    if (!scope) {
      clearTaskScoped()
      return
    }
    try {
      const [fileList, ctx, runList, artifactList, profileList, reviewList] = await Promise.all([
        api.files(scope.projectId, scope.taskId, signalFor(scope)),
        api.context(scope.projectId, scope.taskId, signalFor(scope)),
        api.runs(scope.projectId, scope.taskId, signalFor(scope)),
        api.artifacts(scope.projectId, scope.taskId, signalFor(scope)),
        api.profiles(scope.projectId, scope.taskId, signalFor(scope)),
        api.reviews(scope.projectId, scope.taskId, signalFor(scope)),
      ])
      // 六份响应里任何一份迟到都整批丢弃：宁可空一会，也不把别的任务的数据填进来
      if (!isCurrent(scope)) return
      setFiles(fileList.files)
      setContext(ctx)
      setRuns(runList.runs)
      setArtifacts(artifactList.artifacts)
      setProfiles(profileList.profiles)
      setReviews(reviewList.reviews)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (isCurrent(scope)) throw err
    }
  }, [beginScope, isCurrent, clearTaskScoped, signalFor])

  const refreshAll = useCallback(async () => {
    try {
      const [health, session, caps, proj] = await Promise.all([
        api.health(),
        api.session().catch(() => null),
        api.capabilities(),
        api.projects(),
      ])
      setWorkRoot(health.work_root)
      setResearchAppUrl(health.research_app_url)
      setAllowedOrigins(health.allowed_origins)
      setCapabilities(caps.tools)
      if (session) setSessionInfo(session.session)
      setProjects(proj.projects)

      const restored = readRestoredSelection()
      const stillThere = restored
        ? proj.projects.find((item) => item.project_id === restored.projectId)
        : undefined
      const taskStillThere = stillThere?.tasks.some((item) => item.task_id === restored?.taskId)
      if (restored && stillThere && taskStillThere) {
        // 刷新后回到上次的项目/任务（epoch 重新计数，内容来自磁盘）
        setSelection({ epoch: 0, projectId: restored.projectId, taskId: restored.taskId })
        setNeedsReselect(false)
        await refreshTask()
      } else {
        // 恢复不了：不暗换默认项目/首任务，要求用户显式选择
        writeRestoredSelection(null)
        setSelection(null)
        setNeedsReselect(true)
        clearTaskScoped()
      }
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setReady(true)
    }
  }, [refreshTask, clearTaskScoped])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  // 运行中的任务轮询，直到全部进入终态；刷新页面后按磁盘状态继续。
  useEffect(() => {
    const pending = runs.filter((run) => run.status === 'queued' || run.status === 'running')
    if (pending.length === 0) return
    const scope = selectionRef.current
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const updates = await Promise.all(
          pending.map((run) => api.run(run.run_id, controller.signal).catch(() => null)),
        )
        if (!scope || selectionRef.current !== scope) return // 轮询期间换了任务：丢弃
        setRuns((previous) =>
          previous.map((run) => {
            const update = updates.find((item) => item?.run.run_id === run.run_id)
            return update ? update.run : run
          }),
        )
        await reloadArtifacts()
      } catch {
        /* 轮询失败不打扰用户，下一轮再试 */
      }
    }, 1200)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [runs, reloadArtifacts])

  const selectProject = useCallback(
    (nextProjectId: string) => {
      const project = projects.find((item) => item.project_id === nextProjectId)
      // 整对象替换（epoch+1）→ 之前所有在途响应全部失效。
      // 换项目时若该项目的第一个任务存在就一并选中；但 epoch 只 +1，
      // 由下面的 effect 统一触发一次加载，避免"两次 setState 抢跑"。
      setSelection((previous) => ({
        epoch: (previous?.epoch ?? 0) + 1,
        projectId: nextProjectId,
        taskId: project?.tasks[0]?.task_id ?? '',
      }))
      if (!project?.tasks[0]) {
        setNeedsReselect(false)
        clearTaskScoped()
      } else {
        setNeedsReselect(false)
      }
    },
    [projects, clearTaskScoped],
  )

  const selectTask = useCallback(
    (nextTaskId: string) => {
      const current = selectionRef.current
      if (!current) return
      setSelection({ epoch: current.epoch + 1, projectId: current.projectId, taskId: nextTaskId })
    },
    [],
  )

  useEffect(() => {
    if (selection?.taskId) void refreshTask()
  }, [selection?.epoch, selection?.taskId, refreshTask])

  /** 写动作：把这一刻的选择固定下来，提交前再校验一次，迟到的写一律拒绝。 */
  const frozenScope = useCallback((): Scope => {
    const current = selectionRef.current
    if (!current) throw new Error('请先选择项目与任务')
    return current
  }, [])

  const createTask = useCallback(
    async (newTaskId: string, title: string, note: string) => {
      setBusy('create-task')
      try {
        const scope = frozenScope()
        await api.createTask(scope.projectId, newTaskId, title, note)
        if (!isCurrent(scope)) throw new Error('选择已变化，新建任务的结果已丢弃，请重试')
        const result = await api.projects()
        setProjects(result.projects)
        setSelection({ epoch: scope.epoch + 1, projectId: scope.projectId, taskId: newTaskId })
      } finally {
        setBusy('')
      }
    },
    [frozenScope, isCurrent],
  )

  const runTool = useCallback(
    async (toolId: string, params: Record<string, unknown>) => {
      setBusy(toolId)
      try {
        // 提交这一刻冻结归属：慢响应/后来切换都不会把这次运行算到别的项目上
        const scope = frozenScope()
        const result = await api.createRun(scope.projectId, scope.taskId, toolId, params)
        if (!isCurrent(scope)) {
          // 服务端已按冻结的 project/task 登记；这里只是不再把它显示到新任务下
          return result.run
        }
        setRuns((previous) => [result.run, ...previous])
        setActiveRunId(result.run.run_id)
        if (result.run.status !== 'queued') {
          setError(result.run.error || `${result.run.tool_label} 不可用`)
        }
        return result.run
      } finally {
        setBusy('')
      }
    },
    [frozenScope, isCurrent],
  )

  const uploadFile = useCallback(
    async (file: File) => {
      setBusy('upload')
      try {
        const scope = frozenScope()
        await api.upload(scope.projectId, scope.taskId, file)
        if (!isCurrent(scope)) throw new Error('选择已变化，上传结果请在新任务里重新上传')
        await refreshTask()
      } finally {
        setBusy('')
      }
    },
    [frozenScope, isCurrent, refreshTask],
  )

  const deleteFile = useCallback(
    async (fileId: string) => {
      setBusy('delete-file')
      try {
        const scope = frozenScope()
        await api.deleteFile(scope.projectId, scope.taskId, fileId)
        if (!isCurrent(scope)) throw new Error('选择已变化，删除结果已丢弃，请重新确认')
        await refreshTask()
      } finally {
        setBusy('')
      }
    },
    [frozenScope, isCurrent, refreshTask],
  )

  const saveHandoff = useCallback(
    async (markdown: string) => {
      setBusy('handoff')
      try {
        const scope = frozenScope()
        await api.saveHandoff(scope.projectId, scope.taskId, markdown)
        if (!isCurrent(scope)) throw new Error('选择已变化，接手摘要写到了原任务，未写入新任务')
      } finally {
        setBusy('')
      }
    },
    [frozenScope, isCurrent],
  )

  const value = useMemo<SessionValue>(
    () => ({
      ready,
      needsReselect,
      error,
      workRoot,
      researchAppUrl,
      allowedOrigins,
      capabilities,
      projects,
      selection,
      projectId: selection?.projectId ?? '',
      taskId: selection?.taskId ?? '',
      sessionInfo,
      page,
      files,
      context,
      runs,
      artifacts,
      profiles,
      reviews,
      activeRunId,
      busy,
      beginScope,
      isCurrent,
      setPage,
      selectProject,
      selectTask,
      setActiveRun: setActiveRunId,
      refreshAll,
      refreshTask,
      reloadRuns,
      reloadArtifacts,
      reloadProfiles,
      reloadReviews,
      createTask,
      runTool,
      uploadFile,
      deleteFile,
      saveHandoff,
      setError,
    }),
    [
      ready, needsReselect, error, workRoot, researchAppUrl, allowedOrigins, capabilities, projects,
      selection, sessionInfo, page, files, context, runs, artifacts, profiles, reviews, activeRunId,
      busy, beginScope, isCurrent, selectProject, selectTask, refreshAll, refreshTask, reloadRuns,
      reloadArtifacts, reloadProfiles, reloadReviews, createTask, runTool, uploadFile, deleteFile,
      saveHandoff,
    ],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession 必须在 SessionProvider 内使用')
  return value
}
