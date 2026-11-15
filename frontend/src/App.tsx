import { useCallback, useState } from 'react'
import { ObservationWorkspace, type ObservationWorkflow } from './features/observation/ObservationWorkspace'
import { isDemoModeEnabled } from './api/mocks'
import { SourceLink } from './components/SourceLink'
import { CSAResources } from './features/resources/CSAResources'
import './App.css'

export function App() {
  const [workflow, setWorkflow] = useState<ObservationWorkflow>('now')
  const [previousWorkflow, setPreviousWorkflow] = useState<ObservationWorkflow>('now')
  const openComparison = useCallback(() => {
    if (workflow !== 'comparison') setPreviousWorkflow(workflow)
    setWorkflow('comparison')
  }, [workflow])
  const closeComparison = useCallback(() => setWorkflow(previousWorkflow), [previousWorkflow])
  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-left">
          <span className="brand-mark" aria-hidden="true">◉</span>
          <h1 className="app-title" data-testid="app-title">
            LUNAR NAVIGATOR <span>/ WORKSTATION</span>
          </h1>
        </div>
        {isDemoModeEnabled() && (
          <span className="demo-badge" data-testid="header-demo-badge">
            DEMO HEALTH FIXTURE · Observations use the API
          </span>
        )}
      </header>
      <ObservationWorkspace workflow={workflow} onWorkflowChange={setWorkflow} onOpenComparison={openComparison} onCloseComparison={closeComparison} />
      <footer className="app-footer">
        <span>SOURCES</span>
        <SourceLink url="https://ssd.jpl.nasa.gov/horizons/">Horizons</SourceLink>
        <SourceLink url="https://trek.nasa.gov/moon/">Moon Trek</SourceLink>
        <SourceLink url="https://quickmap.lroc.asu.edu/">LROC</SourceLink>
        <SourceLink url="https://svs.gsfc.nasa.gov/4720/">Moon texture: NASA SVS / LROC WAC and LDAM</SourceLink>
        <details className="csa-source-details"><summary>CSA resources</summary><CSAResources /></details>
        <span className="footer-contract">API v1 · UTC · Backend calculations</span>
        <span className="ai-disclosure">AI-assisted development: Codex · Antigravity</span>
      </footer>
    </div>
  )
}

export default App
