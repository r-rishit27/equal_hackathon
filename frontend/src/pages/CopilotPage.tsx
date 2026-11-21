import { WorkspaceChat } from './WorkspaceChat'
import './copilot.css'

export default function CopilotPage() {
  return <main className="reckon-copilot">
    <header><img src="/favicon.svg" height={38} width={38} alt="" /><h1>Reckon Copilot</h1></header>
    <WorkspaceChat />
  </main>
}
