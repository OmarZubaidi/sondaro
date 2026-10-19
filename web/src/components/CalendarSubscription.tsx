import { useRef, useState } from 'react'

const PATH = '/sondaro.ics'

interface Props {
  /** the tailnet address, worked out by the api. Empty when it couldn't be. */
  tailnetUrl: string
}

/** The calendar subscription, set up once and then forgotten.
 *
 *  It lives in settings rather than on the pages, because that's what it is:
 *  a thing you do on the day you install this and never again. A button on
 *  every page implied there was something to fetch each visit.
 *
 *  The url is the tailnet one, not the address you're browsing from — a
 *  subscription added on a phone has to survive that phone leaving the house.
 */
export function CalendarSubscription({ tailnetUrl }: Props) {
  const [copied, setCopied] = useState(false)
  const field = useRef<HTMLInputElement>(null)

  const origin =
    tailnetUrl.replace(/\/+$/, '') ||
    (typeof window === 'undefined' ? '' : window.location.origin)
  const url = `${origin}${PATH}`
  const webcal = url.replace(/^https?:/, 'webcal:')

  async function copy() {
    field.current?.select()
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      // no clipboard outside a secure context; the field is selected, so the
      // keyboard still works and the button simply doesn't claim otherwise
      setCopied(false)
    }
  }

  return (
    <div className="card">
      <label htmlFor="calendar-url">Subscription URL</label>
      <input
        id="calendar-url"
        ref={field}
        type="text"
        readOnly
        value={url}
        onFocus={(e) => e.currentTarget.select()}
      />
      <div className="row">
        <a className="button-ish" href={webcal}>
          Open in calendar
        </a>
        <button type="button" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <div className="help">
        Add this once. Shows you mark as bought appear in it, and unmarking takes them
        back out. Suggestions never do.
      </div>
      {!tailnetUrl && (
        <div className="note">
          This is the address you're browsing from, which won't resolve off your
          network. The tailnet address is built from the sidecar's hostname and the
          domain in <code>NTFY_URL</code> — set that in <code>.env</code> to fix it.
        </div>
      )}
    </div>
  )
}
