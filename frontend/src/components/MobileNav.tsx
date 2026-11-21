import { useLocation, useNavigate } from 'react-router-dom'
import { MoreHorizontal } from 'lucide-react'
import { useCallback, useState } from 'react'
import { PATHS, pageForPath } from '../routes/paths'
import { useAuth } from '../auth/AuthContext'
import { workspaceNavigation } from './workspaceNavigation'
import { useEntitlements } from '../auth/EntitlementsContext'
import { Modal } from '../ui'

const PRIMARY = ['dashboard', 'bills', 'upload', 'vendors']
/**
 * Bottom navigation for phones and small tablets, where the sidebar is hidden.
 *
 * The audit's E8 finding was that there is no mobile story at all — and approver
 * mobility is the single most-cited reason finance teams buy AP software.
 */
export default function MobileNav({ pendingCount = 0 }: { pendingCount?: number }) {
  const { user } = useAuth()
  const { has } = useEntitlements()
  const navigate = useNavigate()
  const location = useLocation()
  const active = pageForPath(location.pathname)
  const [moreOpen, setMoreOpen] = useState(false)

  const closeMore = useCallback(() => setMoreOpen(false), [])

  if (!user) return null
  const groups = workspaceNavigation(user.role, has)
  const pages = groups.flatMap(group => group.items)
  const primary = PRIMARY.flatMap(page => pages.filter(item => item.page === page))
  const overflow = groups.map(group => ({
    ...group, items: group.items.filter(item => !PRIMARY.includes(item.page)),
  })).filter(group => group.items.length > 0)

  return (
    <>
      <nav className="mn" aria-label="Main">
        {primary.map(({ icon: Icon, label, page }) => (
          <button
            key={page}
            className={`mn__item${active === page ? ' mn__item--active' : ''}`}
            onClick={() => navigate(PATHS[page])}
            aria-current={active === page ? 'page' : undefined}
          >
            <span className="mn__icon">
              <Icon size={19} aria-hidden="true" />
              {page === 'bills' && pendingCount > 0 && <span className="mn__dot" aria-hidden="true" />}
            </span>
            {page === 'upload' ? 'Upload' : label}
          </button>
        ))}
        {overflow.length > 0 && (
          <button
            className={`mn__item${overflow.some(group => group.items.some(item => item.page === active)) ? ' mn__item--active' : ''}`}
            onClick={() => setMoreOpen(true)}
            aria-haspopup="dialog"
          >
            <span className="mn__icon">
              <MoreHorizontal size={19} aria-hidden="true" />
            </span>
            More
          </button>
        )}
      </nav>

      <Modal open={moreOpen} onClose={closeMore} title="All sections" size="sm">
        <div className="workspace-nav-results">
          {overflow.map(group => (
            <section key={group.title}>
              <h3>{group.title}</h3>
              {group.items.map(({ icon: Icon, label, page }) => (
                <button
                  key={page}
                  className="workspace-nav-result"
                  aria-current={active === page ? 'page' : undefined}
                  onClick={() => {
                    closeMore()
                    navigate(PATHS[page])
                  }}
                >
                  <Icon size={17} aria-hidden="true" /> {label}
                </button>
              ))}
            </section>
          ))}
        </div>
      </Modal>
    </>
  )
}
