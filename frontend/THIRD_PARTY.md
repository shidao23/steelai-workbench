# 第三方来源与许可（frontend）

本目录的 React 前端**不是** OpenBB 代码的搬运：它参考了 OpenBB Workspace 的少数小模块机制，
按本项目状态重写。下面逐项登记来源、固定版本、许可与修改内容。

## 1. 改编自 OpenBB Workspace 的文件

- 来源：<https://github.com/OpenBB-finance/workspace>
- 固定提交：`be00e95019a55d57af146919ee46b7e1a4859226`（2026-10-01 归档）
- 上游许可：**Apache-2.0**；上游 `NOTICE` 明确把 **TradingView Advanced Charts 排除在许可之外**
  （本项目未使用该组件）。
- 许可原文副本：`third_party/openbb/LICENSE`（sha256 `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`）
  与 `third_party/openbb/NOTICE`（sha256 `7ead59cd1679b65fb3be5d056b6415564f9c6849b37401c0f0b5020b9dce4c8b`）。
  两个摘要与选读清单 `Batch_WO31/planning_20261013/OPENBB_SOURCE_MANIFEST.json` 完全一致。

| 本目录文件 | 上游文件 | 保留的机制 | 修改内容 |
| --- | --- | --- | --- |
| `src/layout/usePanelsState.ts` | `terminalpro/src/components/LayoutAuth/AppLayout/hooks/usePanelsState.ts` | 左右栏开关 + localStorage 持久化 | 去掉 `react-router-dom` 的 `/admin` 分支与 `usehooks-ts`；改为自带 localStorage；按 `schemaVersion+project+page` 隔离；新增 `resetPanels()` |
| `src/layout/GridLayout.tsx` | `terminalpro/src/components/GridLayout.tsx` | 稳定分栏 + 可缩放 + 布局保存/重置 + 窄屏纵排 | 去掉 `TabContext`/`app`/`theme` store 与上传耦合；去掉拖动排序与拖拽添加 widget（首版不需要）；重新连接 project/page/schemaVersion；补键盘调整与 aria |
| `src/iframe/protocol.ts` | `terminalpro/src/types/iframeProtocol.ts` | Zod 校验的消息 schema 形状 | 去掉 `zod` 依赖改手写校验；命名空间 `openbb-*` → `steelai-*`；**删除 `openbb-auth`/authHeaders 转发**；新增 `projectId`/`taskId`/`frameInstanceId`/`requestId` |
| `src/iframe/registry.ts` | `terminalpro/src/lib/iframeWidgetRegistry.ts` | 已挂载 iframe 的注册表与命令式钩子 | 键改为 `frameInstanceId`；登记 `projectId`/`taskId`；新增项目切换失效、卸载清 pending、请求超时 |
| `src/iframe/IframePanel.tsx` | `terminalpro/src/components/Widgets/Helpers/useIframeProtocol.tsx` | 握手 → 参数 → 数据/错误 → 超时的流程 | **上游「同 origin 即放行」不作为本项目隔离边界**；绑定必须同时校验 `event.origin`、`event.source === iframe.contentWindow`、`projectId`/`taskId`/`frameInstanceId` 一致；不转发凭据；未实现协议时退化为普通 iframe 并标注“未绑定” |
| `src/components/LineChart.tsx` | `terminalpro/src/components/Charting/PlotlyChart.tsx` | 懒加载、按容器尺寸自适应、主题与图对象分离 | 不照搬其全局依赖；轴标题/单位由调用方显式给出，空数据渲染真实空状态 |

**未采用的 OpenBB 部分**：`terminalpro/package.json` 的金融/SSO/遥测依赖树、
OpenBB 的 DB/Redis/SSO/Docker/云模型整栈、上游修改性 lint 脚本、`backend-api` 的 FastAPI 应用。

## 2. 本目录实际安装的 npm 依赖（package-lock.json 已锁定）

| 包 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| `react` | 19.3.0 | MIT | UI |
| `react-dom` | 19.3.0 | MIT | UI |
| `plotly.js-dist-min` | 4.1.2 | MIT | 科研曲线（保留轴标题与单位） |
| `typescript` | 5.9.3 | Apache-2.0 | 类型检查（dev） |
| `vite` | 7.3.7 | MIT | 构建（dev） |
| `@vitejs/plugin-react` | 5.2.0 | MIT | 构建（dev） |
| `@types/react` | 19.3.0 | MIT | 类型（dev） |
| `@types/react-dom` | 19.3.0 | MIT | 类型（dev） |

安装方式：`npm install --ignore-scripts`（本机沙箱阻止 esbuild 的 postinstall 生成子进程；
`@esbuild/win32-x64` 平台包已随锁文件安装，`esbuild --version` 实测返回 `0.28.2`）。

## 3. 明确排除的商业/未授权组件

- TradingView Advanced Charts（上游 NOTICE 已排除）
- AG Grid Enterprise、Highcharts 等需要商业授权的图表/表格组件
- 任何需要 SSO/遥测/云凭据才能运行的上游模块

## 4. 分发说明

对外分发本目录时须同时带上 `third_party/openbb/LICENSE` 与 `third_party/openbb/NOTICE`，
并保留本文件；不得把改编文件统称为本仓原创。
