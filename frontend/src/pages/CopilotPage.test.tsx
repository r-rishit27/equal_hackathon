import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import CopilotPage from './CopilotPage'
import { ConversationProvider } from './WorkspaceChat'

it('opens one conversation for workspace and approval questions', () => {
  render(<MemoryRouter><ConversationProvider><CopilotPage /></ConversationProvider></MemoryRouter>)
  expect(screen.getByRole('heading', {name: 'Reckon Copilot'})).toBeVisible()
  expect(screen.getByRole('button', {name: 'Which bills need attention?'})).toBeVisible()
  expect(screen.getAllByRole('textbox')).toHaveLength(1)
  expect(screen.queryByRole('button', {name: 'Approval evidence'})).toBeNull()
})
