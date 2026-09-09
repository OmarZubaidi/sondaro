import { useState } from 'react'
import { api } from '../lib/api'
import type { Show } from '../lib/types'

/** Marking a ticket bought is what puts a show in the calendar, so it has to
 *  work from every list that shows one. The state lives here because callers
 *  also style themselves off it. */
export function useTicket(show: Show, onChanged?: () => void) {
  // optimistic: the round trip is a single row write, and waiting on it makes
  // the button feel broken
  const [bought, setBought] = useState(show.purchased)
  const [pending, setPending] = useState(false)

  async function toggle() {
    const next = !bought
    setBought(next)
    setPending(true)
    try {
      await api.setPurchased(show.id, next)
      onChanged?.()
    } catch {
      setBought(!next)
    } finally {
      setPending(false)
    }
  }

  return { bought, pending, toggle }
}

interface Props {
  bought: boolean
  pending: boolean
  onToggle: () => void
  /** the compact form, for a dense list of dates */
  terse?: boolean
}

export function TicketToggle({ bought, pending, onToggle, terse = false }: Props) {
  return (
    <button
      type="button"
      className={`ticket-toggle${bought ? ' held' : ''}`}
      aria-pressed={bought}
      aria-label={bought ? 'going' : 'mark as bought'}
      disabled={pending}
      onClick={onToggle}
    >
      {bought ? '✓ going' : terse ? 'going?' : 'mark as bought'}
    </button>
  )
}
