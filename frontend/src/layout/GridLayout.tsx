/**
 * 改编自 OpenBB Workspace `terminalpro/src/components/GridLayout.tsx`
 *
 * 来源：https://github.com/OpenBB-finance/workspace
 * 固定提交：be00e95019a55d57af146919ee46b7e1a4859226
 * 上游许可：Apache-2.0（见 frontend/THIRD_PARTY.md 与 frontend/third_party/openbb/）
 *
 * 修改说明（WO-31 §2）：
 * - 上游耦合 `TabContext`、`app/theme` store 与上传组件，不能原样复制；
 *   这里**只保留“稳定分栏 + 可缩放 + 布局保存/重置”的机制**，重新连接本项目的
 *   project/page/schemaVersion 状态；
 * - 去掉了拖动排序、拖拽添加 widget、响应断点表等首版不需要的自由度
 *   （工单明确“自由拖动不是首版阻碍项”）；
 * - 窄屏自动纵排，键盘可调整分隔条，带 `role="separator"` 与 aria 值。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

export const GRID_SCHEMA_VERSION = 1
const STORAGE_PREFIX = 'steelai-research-grid'
const MIN_RATIO = 0.2
const MAX_RATIO = 0.85

export type GridOrientation = 'columns' | 'rows'

export interface GridState {
  orientation: GridOrientation
  ratio: number
  secondaryVisible: boolean
}

const DEFAULT_GRID: GridState = { orientation: 'columns', ratio: 0.6, secondaryVisible: true }

function storageKey(projectId: string, page: string): string {
  return `${STORAGE_PREFIX}:v${GRID_SCHEMA_VERSION}:${projectId || 'none'}:${page}`
}

function readGrid(key: string): GridState {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return DEFAULT_GRID
    const parsed = JSON.parse(raw) as Partial<GridState>
    return {
      orientation: parsed.orientation === 'rows' ? 'rows' : 'columns',
      ratio: typeof parsed.ratio === 'number' && parsed.ratio >= MIN_RATIO && parsed.ratio <= MAX_RATIO
        ? parsed.ratio
        : DEFAULT_GRID.ratio,
      secondaryVisible: parsed.secondaryVisible !== false,
    }
  } catch {
    return DEFAULT_GRID
  }
}

interface Props {
  projectId: string
  page: string
  primary: ReactNode
  secondary: ReactNode
  primaryLabel: string
  secondaryLabel: string
}

export function GridLayout({ projectId, page, primary, secondary, primaryLabel, secondaryLabel }: Props) {
  const key = useMemo(() => storageKey(projectId, page), [projectId, page])
  const [state, setState] = useState<GridState>(() => readGrid(key))
  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragging = useRef(false)

  useEffect(() => {
    setState(readGrid(key))
  }, [key])

  const persist = useCallback((next: GridState) => {
    setState(next)
    try {
      window.localStorage.setItem(key, JSON.stringify(next))
    } catch {
      /* 存储不可用时只保留内存状态 */
    }
  }, [key])

  const reset = useCallback(() => {
    try {
      window.localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
    setState(DEFAULT_GRID)
  }, [key])

  const applyPointer = useCallback((clientX: number, clientY: number) => {
    const box = containerRef.current?.getBoundingClientRect()
    if (!box) return
    const raw = state.orientation === 'columns'
      ? (clientX - box.left) / box.width
      : (clientY - box.top) / box.height
    const ratio = Math.min(MAX_RATIO, Math.max(MIN_RATIO, raw))
    setState((previous) => ({ ...previous, ratio }))
  }, [state.orientation])

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      if (!dragging.current) return
      event.preventDefault()
      applyPointer(event.clientX, event.clientY)
    }
    const onUp = () => {
      if (!dragging.current) return
      dragging.current = false
      setState((previous) => {
        try {
          window.localStorage.setItem(key, JSON.stringify(previous))
        } catch {
          /* ignore */
        }
        return previous
      })
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
  }, [applyPointer, key])

  const percent = Math.round(state.ratio * 100)

  return (
    <div className="grid-layout">
      <div className="grid-toolbar">
        <span className="muted">分栏</span>
        <button
          type="button"
          className="chip"
          onClick={() => persist({
            ...state,
            orientation: state.orientation === 'columns' ? 'rows' : 'columns',
          })}
        >
          {state.orientation === 'columns' ? '左右分栏' : '上下分栏'}
        </button>
        <button
          type="button"
          className="chip"
          onClick={() => persist({ ...state, secondaryVisible: !state.secondaryVisible })}
        >
          {state.secondaryVisible ? '隐藏次栏' : '显示次栏'}
        </button>
        <button type="button" className="chip" onClick={reset}>恢复默认布局</button>
        <span className="muted small">
          布局按 项目/页面/schema v{GRID_SCHEMA_VERSION} 保存
        </span>
      </div>

      <div
        ref={containerRef}
        className={`grid-body grid-${state.orientation}${state.secondaryVisible ? '' : ' single'}`}
        style={state.secondaryVisible
          ? { gridTemplateColumns: state.orientation === 'columns' ? `${percent}% 6px 1fr` : undefined,
              gridTemplateRows: state.orientation === 'rows' ? `${percent}% 6px 1fr` : undefined }
          : undefined}
      >
        <section className="grid-pane" aria-label={primaryLabel}>
          <header className="pane-head">{primaryLabel}</header>
          <div className="pane-body">{primary}</div>
        </section>

        {state.secondaryVisible && (
          <div
            role="separator"
            aria-orientation={state.orientation === 'columns' ? 'vertical' : 'horizontal'}
            aria-valuenow={percent}
            aria-valuemin={MIN_RATIO * 100}
            aria-valuemax={MAX_RATIO * 100}
            tabIndex={0}
            className="grid-split"
            onPointerDown={() => { dragging.current = true }}
            onKeyDown={(event) => {
              const step = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -0.03
                : event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 0.03 : 0
              if (!step) return
              event.preventDefault()
              persist({
                ...state,
                ratio: Math.min(MAX_RATIO, Math.max(MIN_RATIO, state.ratio + step)),
              })
            }}
          />
        )}

        {state.secondaryVisible && (
          <section className="grid-pane" aria-label={secondaryLabel}>
            <header className="pane-head">{secondaryLabel}</header>
            <div className="pane-body">{secondary}</div>
          </section>
        )}
      </div>
    </div>
  )
}
