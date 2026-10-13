/**
 * 科研旧页嵌入面板。
 *
 * 改编自 OpenBB Workspace `terminalpro/src/components/Widgets/Helpers/useIframeProtocol.tsx`
 * 的**流程**（握手 → 参数 → 数据/错误 → 超时），但重做了可信绑定：
 *
 * - 上游“同 origin 即放行”的分支**不作为本项目的隔离边界**；
 * - 绑定必须同时满足：`event.origin` 在白名单内、`event.source === iframe.contentWindow`、
 *   消息里的 `projectId`/`taskId`/`frameInstanceId` 与当前实例一致；
 * - **不向 iframe 转发任何凭据**（协议里已删除 authHeaders）；
 * - 目标页没有实现协议时，退化为普通 iframe，并明确标注“未绑定”，不把嵌入成功当成接通。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  newRequestId,
  parseConnectMessage,
  parseDataMessage,
  parseErrorMessage,
  type ConnectMessage,
} from './protocol'
import { registerIframeWidget, settleRequest, trackRequest, unregisterIframeWidget } from './registry'

interface Props {
  title: string
  url: string
  allowedOrigins: string[]
  projectId: string
  taskId: string
  note: string
}

type BindingState = 'loading' | 'bound' | 'unbound'

export function IframePanel({ title, url, allowedOrigins, projectId, taskId, note }: Props) {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const [state, setState] = useState<BindingState>('loading')
  const [detail, setDetail] = useState('等待页面加载并尝试握手…')
  const [manifest, setManifest] = useState<ConnectMessage | null>(null)
  const [data, setData] = useState<unknown>(null)

  const frameInstanceId = useMemo(
    () => `frame-${projectId}-${taskId}-${Math.random().toString(16).slice(2, 8)}`,
    [projectId, taskId],
  )

  useEffect(() => {
    const targetOrigin = (() => {
      try {
        return new URL(url, window.location.href).origin
      } catch {
        return ''
      }
    })()

    function onMessage(event: MessageEvent) {
      if (!allowedOrigins.includes(event.origin)) return
      if (event.source !== frameRef.current?.contentWindow) return

      const connect = parseConnectMessage(event.data)
      if (connect) {
        if (connect.frameInstanceId !== frameInstanceId
          || connect.projectId !== projectId
          || connect.taskId !== taskId) {
          setDetail('收到其他实例/其他项目的握手，已忽略（不会串任务）。')
          return
        }
        setManifest(connect)
        setState('bound')
        setDetail(`已绑定：${connect.widgets.length} 个子组件`)
        registerIframeWidget(frameInstanceId, {
          projectId,
          taskId,
          manifest: connect.widgets,
          requestData: (widgetId, requestId) => new Promise((resolve, reject) => {
            trackRequest(frameInstanceId, widgetId, requestId, resolve, reject)
            frameRef.current?.contentWindow?.postMessage({
              type: 'steelai-request',
              frameInstanceId,
              requestId,
              projectId,
              taskId,
              widgetId,
            }, targetOrigin)
          }),
          sendRefresh: () => {
            if (frameRef.current) frameRef.current.src = frameRef.current.src
          },
        })
        return
      }

      const incoming = parseDataMessage(event.data)
      if (incoming && incoming.frameInstanceId === frameInstanceId) {
        settleRequest(incoming)
        setData(incoming.data)
        return
      }
      const failure = parseErrorMessage(event.data)
      if (failure && failure.frameInstanceId === frameInstanceId) {
        setDetail(`页面报告错误：${failure.error}`)
      }
    }

    window.addEventListener('message', onMessage)
    const timer = window.setTimeout(() => {
      setState((previous) => {
        if (previous === 'loading') {
          setDetail('该页未在 8s 内完成消息握手：按普通 iframe 嵌入，仅显示原页，不当作已接通。')
          return 'unbound'
        }
        return previous
      })
    }, 8000)

    return () => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(timer)
      unregisterIframeWidget(frameInstanceId)
    }
  }, [allowedOrigins, frameInstanceId, projectId, taskId, url])

  return (
    <div className="iframe-panel">
      <header className="iframe-head">
        <div>
          <strong>{title}</strong>
          <div className="muted small">{note}</div>
        </div>
        <div className="iframe-status">
          <span className={state === 'bound' ? 'badge badge-ok' : state === 'unbound' ? 'badge badge-warn' : 'badge badge-busy'}>
            {state === 'bound' ? '消息已绑定' : state === 'unbound' ? '未绑定（普通嵌入）' : '加载中'}
          </span>
          <a className="chip" href={url} target="_blank" rel="noreferrer noopener">在新窗口打开原页</a>
        </div>
      </header>
      <p className="muted small">{detail}</p>
      <iframe
        ref={frameRef}
        title={title}
        src={url}
        className="iframe-body"
        sandbox="allow-scripts allow-same-origin allow-forms allow-downloads"
      />
      {manifest && (
        <div className="muted small">
          已声明子组件：{manifest.widgets.map((item) => item.name).join('、') || '（无）'}
        </div>
      )}
      {data !== null && (
        <details>
          <summary>最近一次数据消息</summary>
          <pre className="code-block small">{JSON.stringify(data, null, 2).slice(0, 2000)}</pre>
        </details>
      )}
      <button
        type="button"
        className="chip"
        onClick={() => {
          const requestId = newRequestId()
          setDetail(`已发出 requestId=${requestId}（若页面未实现协议则不会有响应）`)
        }}
      >
        生成一个 requestId 示例
      </button>
    </div>
  )
}
