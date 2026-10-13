import { SessionProvider, useSession } from './state/session'
import { AppShell } from './layout/AppShell'
import { AiPanel } from './components/AiPanel'
import { ErrorBanner, EmptyState } from './components/ui'
import { ProjectsPage } from './pages/ProjectsPage'
import { FilesPage } from './pages/FilesPage'
import { DataProcessingPage } from './pages/DataProcessingPage'
import { ToolsPage } from './pages/ToolsPage'
import { ArtifactsPage } from './pages/ArtifactsPage'
import { WorkLogPage } from './pages/WorkLogPage'

function Router() {
  const session = useSession()
  switch (session.page) {
    case 'files':
      return <FilesPage />
    case 'data_processing':
      return <DataProcessingPage />
    case 'tools':
      return <ToolsPage />
    case 'artifacts':
      return <ArtifactsPage />
    case 'work_log':
      return <WorkLogPage />
    case 'projects':
    default:
      return <ProjectsPage />
  }
}

function Body() {
  const session = useSession()
  if (!session.ready) {
    return <div className="boot">正在连接本机薄 API…</div>
  }
  return (
    <>
      <ErrorBanner message={session.error} onClose={() => session.setError('')} />
      {session.projects.length === 0 && !session.error && (
        <EmptyState
          title="没有读到项目"
          hint="薄 API 已连通，但科研主表里没有项目行，也没有合成演示项目。"
        />
      )}
      <Router />
    </>
  )
}

export default function App() {
  return (
    <SessionProvider>
      <AppShell aiPanel={<AiPanel />}>
        <Body />
      </AppShell>
    </SessionProvider>
  )
}
