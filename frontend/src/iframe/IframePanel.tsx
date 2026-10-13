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
 *
 * WO-32 §3 修复：URL 由服务端 `.../research-url` 按当前 project/task 构建并校验，
 * 这里不再接受任意地址；project/task 切换会换 URL 并重载 iframe，
 * 旧绑定立刻失效（不残留上一个任务的上下文）。原来那个"生成一个 requestId 示例"
 * 的演示按钮已删除——它不是功能，只是噪声。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  parseConnectMessage,
  parseDataMessage,
  parseErrorMessage,
  type ConnectMessage,
} from './protocol'
import { registerIframeWidget, settleRequest, trackRequest, unregisterIframeWidget } from './registry'

interface Props {
  title: string
  /** 服务端构建并校验过的 URL（带 project_id / task_id），切换即换值 */
  url: string
  allowedOrigins: string[]
  projectId: string
  taskId: string
  note: string
}

type BindingState = 'loading' | 'bound' | 'unbound'

export function IframePanel({ title, url, allowedOrigins, projectId, taskId, note }: Props) {
  const frameRef = useRef<HTMLIFrameElement | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [state, setState] = useState<BindingState>('loading')
  const [detail, setDetail] = useState('等待页面加载并尝试握手…')
  const [manifest, setManifest] = useState<ConnectMessage | null>(null)
  const [data, setData] = useState<unknown>(null)

  const frameInstanceId = useMemo(
    () => `frame-${projectId}-${taskId}-${reloadKey}-${Math.random().toString(16).slice(2, 8)}`,
    [projectId, taskId, reloadKey],
  )

  // project/task 或 URL 变化：作废旧绑定并重载 iframe（旧任务的上下文不得残留）
  useEffect(() => {
    setState('loading')
    setManifest(null)
    setData(null)
    setDetail('作用域已变化，重新加载原页并尝试握手…')
    setReloadKey((key) => key + 1)
  }, [projectId, taskId, url])

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
          <button type="button" className="chip" onClick={() => setReloadKey((key) => key + 1)}>
            重新载入
          </button>
          <a className="chip" href={url} target="_blank" rel="noreferrer noopener">在新窗口打开原页</a>
        </div>
      </header>
      <p className="muted small">{detail}</p>
      <iframe
        key={`${url}#${reloadKey}`}
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
      <p className="muted small">
        该地址由服务端按当前 <code>{projectId || '未选择'}</code> / <code>{taskId || '未选择'}</code> 构建并校验，
        不接受页面任意填写的 URL；消息协议是可选增强，没实现就按普通 iframe 显示原页。
      </p>
    </div>
  )
}
