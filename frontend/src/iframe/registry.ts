/**
 * 改编自 OpenBB Workspace `terminalpro/src/lib/iframeWidgetRegistry.ts`
 *
 * 来源：https://github.com/OpenBB-finance/workspace
 * 固定提交：be00e95019a55d57af146919ee46b7e1a4859226
 * 上游许可：Apache-2.0（见 frontend/THIRD_PARTY.md 与 frontend/third_party/openbb/）
 *
 * 修改说明（WO-31 §2/§4）：
 * - 上游以 `parentUuid` 为键；这里改为 `frameInstanceId`，并把 `projectId`/`taskId`
 *   一起登记，用于**项目切换失效**；
 * - 新增 pending 请求表：注销（iframe 卸载/切项目）时清掉未决请求，
 *   每个请求带超时，超时后拒绝且不污染后来的同名请求；
 * - 去掉 Copilot/MCP 相关描述，只保留本项目需要的 `requestData` 与 `refresh`。
 */

import type { DataMessage } from './protocol'

export interface IframeWidgetEntry {
  projectId: string
  taskId: string
  requestData: (widgetId: string, requestId: string) => Promise<DataMessage>
  sendRefresh: () => void
  manifest: { widgetId: string; name: string; dataType: 'table' | 'markdown' }[]
}

interface PendingRequest {
  requestId: string
  widgetId: string
  resolve: (message: DataMessage) => void
  reject: (error: Error) => void
  timer: number
}

const registry = new Map<string, IframeWidgetEntry>()
const pending = new Map<string, PendingRequest>()

export const REQUEST_TIMEOUT_MS = 15000

export function registerIframeWidget(frameInstanceId: string, entry: IframeWidgetEntry): void {
  registry.set(frameInstanceId, entry)
}

export function unregisterIframeWidget(frameInstanceId: string): void {
  registry.delete(frameInstanceId)
  for (const [requestId, item] of pending) {
    if (requestId.startsWith(`${frameInstanceId}:`)) {
      window.clearTimeout(item.timer)
      item.reject(new Error('iframe 已卸载，请求取消'))
      pending.delete(requestId)
    }
  }
}

export function getIframeWidget(frameInstanceId: string): IframeWidgetEntry | undefined {
  return registry.get(frameInstanceId)
}

/** 项目/任务切换时让所有已挂载 iframe 的登记失效。 */
export function invalidateProjectScope(): void {
  for (const frameInstanceId of [...registry.keys()]) unregisterIframeWidget(frameInstanceId)
}

export function trackRequest(
  frameInstanceId: string,
  widgetId: string,
  requestId: string,
  resolve: (message: DataMessage) => void,
  reject: (error: Error) => void,
  timeoutMs = REQUEST_TIMEOUT_MS,
): void {
  const key = `${frameInstanceId}:${requestId}`
  const timer = window.setTimeout(() => {
    pending.delete(key)
    reject(new Error(`请求超时（${timeoutMs}ms）：${widgetId}`))
  }, timeoutMs)
  pending.set(key, { requestId, widgetId, resolve, reject, timer })
}

/** 用一条到达的数据消息结算对应的未决请求；返回是否匹配成功。 */
export function settleRequest(message: DataMessage): boolean {
  const key = `${message.frameInstanceId}:${message.requestId}`
  const item = pending.get(key)
  if (!item) return false
  window.clearTimeout(item.timer)
  pending.delete(key)
  item.resolve(message)
  return true
}

export function pendingCount(): number {
  return pending.size
}

export function resetRegistry(): void {
  for (const frameInstanceId of [...registry.keys()]) unregisterIframeWidget(frameInstanceId)
  registry.clear()
  pending.clear()
}
