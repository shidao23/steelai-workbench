/**
 * 改编自 OpenBB Workspace `terminalpro/src/types/iframeProtocol.ts`
 *
 * 来源：https://github.com/OpenBB-finance/workspace
 * 固定提交：be00e95019a55d57af146919ee46b7e1a4859226
 * 上游许可：Apache-2.0（见 frontend/THIRD_PARTY.md 与 frontend/third_party/openbb/）
 *
 * 修改说明（WO-31 §2/§4）：
 * - 去掉 `zod` 依赖，改为**手写校验器**（本仓不引入未审阅的运行时依赖）；
 * - 去掉金融字段（`openbb-*` 命名空间改为本项目 `steelai-*`）；
 * - **删除 `openbb-auth` / authHeaders 转发**：本前端不向 iframe 转发任何凭据；
 * - 新增 `projectId` / `taskId` / `frameInstanceId` / `requestId`，
 *   用于把消息绑定到**当前**项目、当前任务、当前 frame 实例与当前请求；
 * - `openbb-request` 保留为 `steelai-request`，但不再有 `null` 通配。
 */

export type WidgetDataType = 'table' | 'markdown'

export interface WidgetManifest {
  widgetId: string
  name: string
  description?: string
  category?: string
  dataType: WidgetDataType
}

export interface ParamDef {
  paramName: string
  label?: string
  type: 'text' | 'number' | 'date' | 'boolean'
  description?: string
  value?: string
  options?: { label: string; value: string }[]
}

export interface ConnectMessage {
  type: 'steelai-connect'
  projectId: string
  taskId: string
  frameInstanceId: string
  widgets: WidgetManifest[]
  params?: ParamDef[]
}

export interface DataMessage {
  type: 'steelai-data'
  frameInstanceId: string
  requestId: string
  widgetId: string
  dataType: WidgetDataType
  data: Record<string, unknown>[] | string
  columns?: string[]
}

export interface ErrorMessage {
  type: 'steelai-error'
  frameInstanceId: string
  requestId?: string
  widgetId?: string
  error: string
}

export interface RequestMessage {
  type: 'steelai-request'
  frameInstanceId: string
  requestId: string
  projectId: string
  taskId: string
  widgetId: string
}

export interface ContextMessage {
  type: 'steelai-context'
  projectId: string
  taskId: string
  /** 只包含项目/任务标识与说明，不含任何凭据。 */
  note: string
}

export const PARAMS_UPDATE_TYPES = ['steelai:widget-params:update', 'steelai:params:update'] as const
export type ParamsUpdateType = (typeof PARAMS_UPDATE_TYPES)[number]

export interface ParamsUpdateMessage {
  type: ParamsUpdateType
  params?: Record<string, unknown>
  paramName?: string
  value?: unknown
}

// ------------------------------ 手写校验器 ------------------------------ //

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isWidgetDataType(value: unknown): value is WidgetDataType {
  return value === 'table' || value === 'markdown'
}

export function isWidgetManifest(value: unknown): value is WidgetManifest {
  if (!isRecord(value)) return false
  if (!isNonEmptyString(value.widgetId) || !isNonEmptyString(value.name)) return false
  if (!isWidgetDataType(value.dataType)) return false
  if (value.description !== undefined && typeof value.description !== 'string') return false
  if (value.category !== undefined && typeof value.category !== 'string') return false
  return true
}

export function parseConnectMessage(data: unknown): ConnectMessage | null {
  if (!isRecord(data) || data.type !== 'steelai-connect') return null
  if (!isNonEmptyString(data.projectId) || !isNonEmptyString(data.taskId)) return null
  if (!isNonEmptyString(data.frameInstanceId)) return null
  if (!Array.isArray(data.widgets) || !data.widgets.every(isWidgetManifest)) return null
  return {
    type: 'steelai-connect',
    projectId: data.projectId,
    taskId: data.taskId,
    frameInstanceId: data.frameInstanceId,
    widgets: data.widgets as WidgetManifest[],
    params: Array.isArray(data.params) ? (data.params as ParamDef[]) : undefined,
  }
}

export function parseDataMessage(data: unknown): DataMessage | null {
  if (!isRecord(data) || data.type !== 'steelai-data') return null
  if (!isNonEmptyString(data.frameInstanceId) || !isNonEmptyString(data.requestId)) return null
  if (!isNonEmptyString(data.widgetId) || !isWidgetDataType(data.dataType)) return null
  const payload = data.data
  const isTable = Array.isArray(payload) && payload.every(isRecord)
  if (!isTable && typeof payload !== 'string') return null
  return {
    type: 'steelai-data',
    frameInstanceId: data.frameInstanceId,
    requestId: data.requestId,
    widgetId: data.widgetId,
    dataType: data.dataType,
    data: payload as Record<string, unknown>[] | string,
    columns: Array.isArray(data.columns) ? (data.columns as string[]) : undefined,
  }
}

export function parseErrorMessage(data: unknown): ErrorMessage | null {
  if (!isRecord(data) || data.type !== 'steelai-error') return null
  if (!isNonEmptyString(data.frameInstanceId) || !isNonEmptyString(data.error)) return null
  return {
    type: 'steelai-error',
    frameInstanceId: data.frameInstanceId,
    requestId: isNonEmptyString(data.requestId) ? data.requestId : undefined,
    widgetId: isNonEmptyString(data.widgetId) ? data.widgetId : undefined,
    error: data.error,
  }
}

export function isParamsUpdateType(value: unknown): value is ParamsUpdateType {
  return typeof value === 'string' && (PARAMS_UPDATE_TYPES as readonly string[]).includes(value)
}

export function parseParamsMessage(data: unknown): Record<string, unknown> | null {
  if (!isRecord(data) || !isParamsUpdateType(data.type)) return null
  const result: Record<string, unknown> = {}
  if (isRecord(data.params)) {
    for (const [key, value] of Object.entries(data.params)) result[key] = value
  }
  if (isNonEmptyString(data.paramName)) result[data.paramName] = data.value ?? null
  return result
}

export function stringifyParamValue(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (Array.isArray(value)) {
    return value.filter((item) => item !== null).map((item) => String(item)).join(',')
  }
  return String(value)
}

export function newRequestId(): string {
  return `req-${Math.random().toString(16).slice(2, 10)}-${Date.now().toString(36)}`
}
