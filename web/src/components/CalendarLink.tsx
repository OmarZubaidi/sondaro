import { useEffect, useRef, useState } from 'react'
import { CalendarIcon, IconButton } from './IconButton'

const PATH = '/sondaro.ics'

/** Hands over the subscription URL rather than a file.
 *
 *  A downloaded .ics is a snapshot: correct the day you saved it, wrong the
 *  moment you mark another ticket. What the feed is for is being subscribed to
 *  once, so the button gives you the URL to subscribe with.
 *
 *  The clipboard API needs a secure context and this usually runs over plain
 *  http on a tailnet, so the URL is always shown in a selected field — copying
 *  works whether or not the button does.
 */
export function CalendarLink() {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const field = useRef<HTMLInputElement>(null)
  const wrapper = useRef<HTMLDivElement>(null)

  const url = typeof window === 'undefined' ? PATH : `${window.location.origin}${PATH}`
  const webcal =
    typeof window === 'undefined' ? PATH : `webcal://${window.location.host}${PATH}`

  useEffect(() => {
    if (!open) return
    field.current?.select()

    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onClick = (e: MouseEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  async function copy() {
    field.current?.select()
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      // no clipboard over plain http; the field is selected, so Cmd-C works
      setCopied(false)
    }
  }

  return (
    <div className="calendar-link" ref={wrapper}>
      <IconButton
        label="Calendar subscription"
        icon={<CalendarIcon />}
        onClick={() => {
          setCopied(false)
          setOpen((was) => !was)
        }}
      />
      {open && (
        <div className="calendar-pop card" role="dialog" aria-label="Calendar subscription">
          <p className="muted">
            Add this to your calendar once. Shows you mark as bought appear in it, and
            unmarking takes them back out.
          </p>
          <input ref={field} type="text" readOnly value={url} aria-label="Subscription URL" />
          <div className="row">
            <a className="button-ish" href={webcal}>
              Open in calendar
            </a>
            <button type="button" onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
