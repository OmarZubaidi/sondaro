import { useEffect } from 'react'
import { Settings } from '../routes/Settings'
import { CloseIcon, IconButton } from './IconButton'

interface Props {
  open: boolean
  onClose: () => void
}

/** Settings slides in over whatever you were looking at.
 *
 *  There are few enough of them now that a whole page was mostly empty space,
 *  and they're the sort of thing you change *because* of what's on screen —
 *  navigating away from it to do so lost the reason you were changing them.
 *
 *  Kept mounted so the panel can transition; nothing inside it fetches until
 *  it's actually opened. */
export function SettingsDrawer({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        className={`scrim${open ? ' shown' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      {/* a closed drawer is `visibility: hidden`, not just off-screen, so Tab
          can't walk into it and screen readers don't announce it */}
      <aside className={`drawer${open ? ' shown' : ''}`} aria-label="Settings">
        <div className="drawer-head">
          <h1>Settings</h1>
          <IconButton label="Close settings" icon={<CloseIcon />} onClick={onClose} />
        </div>
        <div className="drawer-body">{open && <Settings />}</div>
      </aside>
    </>
  )
}
