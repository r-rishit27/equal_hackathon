import { useCallback, useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useEntitlements } from '../auth/EntitlementsContext'
import { PATHS, pageForPath } from '../routes/paths'
import { Modal } from '../ui'
import { workspaceNavigation } from './workspaceNavigation'

export default function WorkspaceSearch() {
  const { user } = useAuth()
  const { has } = useEntitlements()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const close = useCallback(() => setOpen(false), [])

  useEffect(() => {
    function onShortcut(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.altKey || event.shiftKey ||
        !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k' ||
        document.querySelector('[aria-modal="true"]')) return
      event.preventDefault()
      setQuery('')
      setOpen(true)
    }
    window.addEventListener('keydown', onShortcut)
    return () => window.removeEventListener('keydown', onShortcut)
  }, [])

  const normalizedQuery = query.trim().toLowerCase()
  const terms = normalizedQuery.split(/\s+/)
  const groups = workspaceNavigation(user?.role, has).map(group => ({
    ...group,
    items: group.items.filter(item =>
      terms.every(term => `${group.title} ${item.label}`.toLowerCase().includes(term)),
    ),
  })).filter(group => group.items.length)
  const matches = groups.flatMap(group => group.items)
  const exactMatch = matches.find(item => item.label.toLowerCase() === normalizedQuery)
  const submitMatch = exactMatch ?? (matches.length === 1 ? matches[0] : undefined)

  function go(page: keyof typeof PATHS) {
    setOpen(false)
    navigate(PATHS[page])
  }

  return (
    <>
      <button type="button" className="tb__search" aria-label="Search workspace" aria-haspopup="dialog"
        aria-keyshortcuts="Control+K Meta+K"
        onClick={() => { setQuery(''); setOpen(true) }}>
        <Search size={16} aria-hidden="true" />
        <span>Search</span>
        <kbd aria-hidden="true">Ctrl K</kbd>
      </button>
      <Modal open={open} onClose={close} title="Search workspace" className="workspace-search">
        <form onSubmit={event => { event.preventDefault(); if (submitMatch) go(submitMatch.page) }}>
          <label className="workspace-search__field">
            <Search size={18} aria-hidden="true" />
            <input type="search" data-autofocus aria-label="Find a workspace page"
              placeholder="Find a page by name" value={query} onChange={event => setQuery(event.target.value)} />
          </label>
        </form>
        <div className="workspace-nav-results">
          {groups.length === 0 && <p role="status">No matching pages</p>}
          {groups.map(group => (
            <section key={group.title}>
              <h3>{group.title}</h3>
              {group.items.map(({ icon: Icon, label, page }) => (
                <button key={page} type="button" className="workspace-nav-result"
                  aria-current={pageForPath(pathname) === page ? 'page' : undefined} onClick={() => go(page)}>
                  <Icon size={17} aria-hidden="true" />{label}
                </button>
              ))}
            </section>
          ))}
        </div>
      </Modal>
    </>
  )
}
