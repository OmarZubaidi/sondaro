import { useState } from 'react'
import { api } from '../lib/api'
import type { Show } from '../lib/types'
import { driveTime, isWeekend, place, timeRange } from '../lib/format'
import { FlagChip } from './FlagChip'
import { ScoreBar } from './ScoreBar'

interface Props {
  show: Show
  selected?: boolean
  onToggle?: (show: Show) => void
  showDate?: boolean
  /** Called after the ticket state changes, so the list can re-filter. */
  onChanged?: () => void
}

export function ShowCard({
  show,
  selected = false,
  onToggle,
  showDate = true,
  onChanged,
}: Props) {
  const drive = driveTime(show)
  const hours = timeRange(show)
  const weekend = isWeekend(show.date)
  const interactive = Boolean(onToggle)
  // optimistic: the round trip is a single row write, and waiting on it makes
  // the button feel broken
  const [bought, setBought] = useState(show.purchased)
  const [pending, setPending] = useState(false)

  async function toggleBought() {
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

  const body = (
    <>
      {showDate && (
        <div className="when">
          <span className={weekend ? 'weekend' : undefined}>{show.date}</span>
          {hours && (
            <>
              <br />
              <span className="muted hours">{hours}</span>
            </>
          )}
        </div>
      )}
      <div className="body">
        <div className="artist">{show.artist}</div>
        <div className="where">{place(show) || 'venue to be announced'}</div>
        {drive && (
          <div className="drive">
            {drive} drive
            {show.km !== null && <span className="muted"> · {Math.round(show.km)} km</span>}
          </div>
        )}
        <div className="chips">
          {bought && <span className="chip good">ticket bought</span>}
          {show.trips?.map((trip) => (
            <span className="chip info" key={trip.id}>
              {trip.name}
            </span>
          ))}
          {show.reasons.map((reason) => (
            <span className="chip" key={reason}>
              {reason}
            </span>
          ))}
          {show.flags.map((flag) => (
            <FlagChip flag={flag} key={flag} />
          ))}
        </div>
      </div>
      <ScoreBar score={show.score} />
    </>
  )

  const className = `show${interactive ? ' selectable' : ''}${selected ? ' selected' : ''}`

  return (
    <div className={`card${selected ? ' selected' : ''}${bought ? ' held' : ''}`}>
      {interactive ? (
        <button
          type="button"
          className={className}
          aria-pressed={selected}
          onClick={() => onToggle?.(show)}
        >
          {body}
        </button>
      ) : (
        <div className={className}>{body}</div>
      )}
      <div className="card-foot">
        {show.url && (
          <a href={show.url} target="_blank" rel="noreferrer">
            tickets ↗
          </a>
        )}
        <button
          type="button"
          className={`ticket-toggle${bought ? ' held' : ''}`}
          aria-pressed={bought}
          disabled={pending}
          onClick={toggleBought}
        >
          {bought ? '✓ going' : 'mark as bought'}
        </button>
      </div>
    </div>
  )
}
