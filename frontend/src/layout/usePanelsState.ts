/**
 * 改编自 OpenBB Workspace `terminalpro/src/components/LayoutAuth/AppLayout/hooks/usePanelsState.ts`
 *
 * 来源：https://github.com/OpenBB-finance/workspace
 * 固定提交：be00e95019a55d57af146919ee46b7e1a4859226
 * 上游许可：Apache-2.0（见 frontend/THIRD_PARTY.md 与 frontend/third_party/openbb/）
 *
 * 修改说明（WO-31 §2）：
 * - 去掉 `react-router-dom` 的 `/admin` 分支与 `usehooks-ts` 依赖，改为自带 localStorage 读写；
 * - 状态按 `schemaVersion + project + page` 隔离，换项目/换页不会串用别人的栏位状态；
 * - 增加显式 `resetPanels()`，对应“布局可重置”的要求；
 * - 只保留左右栏与折叠位，不再保留 admin 专用键。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

export type PanelSide = 'left' | 'right'

export interface PanelsState {
  left: boolean
  right: boolean
  collapsedLeft: boolean
  collapsedRight: boolean
  splitRatio: number
}

export const PANELS_SCHEMA_VERSION = 1
const STORAGE_PREFIX = 'steelai-research-panels'

export const DEFAULT_PANELS: PanelsState = {
  left: true,
  right: true,
  collapsedLeft: false,
  collapsedRight: false,
  splitRatio: 0.62,
}

export function panelStorageKey(projectId: string, page: string): string {
  return `${STORAGE_PREFIX}:v${PANELS_SCHEMA_VERSION}:${projectId || 'none'}:${page}`
}

function readPanels(key: string): PanelsState {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return DEFAULT_PANELS
    const parsed = JSON.parse(raw) as Partial<PanelsState>
    return {
      left: typeof parsed.left === 'boolean' ? parsed.left : DEFAULT_PANELS.left,
      right: typeof parsed.right === 'boolean' ? parsed.right : DEFAULT_PANELS.right,
      collapsedLeft: typeof parsed.collapsedLeft === 'boolean' ? parsed.collapsedLeft : DEFAULT_PANELS.collapsedLeft,
      collapsedRight: typeof parsed.collapsedRight === 'boolean' ? parsed.collapsedRight : DEFAULT_PANELS.collapsedRight,
      splitRatio: typeof parsed.splitRatio === 'number' && parsed.splitRatio > 0.2 && parsed.splitRatio < 0.9
        ? parsed.splitRatio
        : DEFAULT_PANELS.splitRatio,
    }
  } catch {
    return DEFAULT_PANELS
  }
}

export function usePanelsState(projectId: string, page: string) {
  const key = useMemo(() => panelStorageKey(projectId, page), [projectId, page])
  const [state, setState] = useState<PanelsState>(() => readPanels(key))

  // 换项目/换页时重新读该组合自己的布局，而不是沿用上一个。
  useEffect(() => {
    setState(readPanels(key))
  }, [key])

  const update = useCallback((patch: Partial<PanelsState>) => {
    setState((previous) => {
      const next = { ...previous, ...patch }
      try {
        window.localStorage.setItem(key, JSON.stringify(next))
      } catch {
        /* 存储不可用时只保留内存状态 */
      }
      return next
    })
  }, [key])

  const resetPanels = useCallback(() => {
    try {
      window.localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
    setState(DEFAULT_PANELS)
  }, [key])

  return { panels: state, update, resetPanels, storageKey: key }
}
