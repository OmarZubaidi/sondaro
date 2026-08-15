import type { Show } from '../lib/types'
import { prettyDate } from '../lib/format'
import { haversineMiles, hopSeverity } from '../lib/distance'

interface Props {
  picks: Show[]
  onRemove: (show: Show) => void
}

interface Leg {
  from: Show
  to: Show
  miles: number
  nights: number
  severity: 'fine' | 'long' | 'implausible'
}

export function buildLegs(picks: Show[]): Leg[] {
  const ordered = [...picks].sort((a, b) => a.date.localeCompare(b.date))
  const legs: Leg[] = []

  for (let i = 1; i < ordered.length; i += 1) {
    const from = ordered[i - 1]
    const to = ordered[i]
    if (from.lat === null || from.lon === null || to.lat === null || to.lon === null) {
      continue
    }
    const miles = haversineMiles(from.lat, from.lon, to.lat, to.lon)
    const nights = Math.max(
      0,
      Math.round(
        (new Date(`${to.date}T12:00:00`).getTime() -
          new Date(`${from.date}T12:00:00`).getTime()) /
          86_400_000,
      ),
    )
    legs.push({ from, to, miles, nights, severity: hopSeverity(miles, nights) })
  }
  return legs
}

/** Selecting shows annotates what each choice costs in travel. It never
 *  removes an option or picks one for you — it just tells you that Wednesday
 *  in Lisbon after Tuesday in Berlin is 1,500 miles. */
export function ItineraryBuilder({ picks, onRemove }: Props) {
  if (picks.length === 0) {
    return (
      <div className="empty">
        Tap shows to build an itinerary. Travel between your picks gets worked out
        as you go — nothing is chosen for you.
      </div>
    )
  }

  const ordered = [...picks].sort((a, b) => a.date.localeCompare(b.date))
  const legs = buildLegs(ordered)
  const total = legs.reduce((sum, leg) => sum + leg.miles, 0)
  const problems = legs.filter((leg) => leg.severity !== 'fine')

  return (
    <div className="stack">
      <div className="statusbar">
        <span>
          {ordered.length} show{ordered.length === 1 ? '' : 's'}
        </span>
        {legs.length > 0 && <span>{Math.round(total)} mi of travel</span>}
        {problems.length > 0 && (
          <span style={{ color: 'var(--warm)' }}>
            {problems.length} awkward jump{problems.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      {ordered.map((show, index) => {
        const leg = legs[index - 1]
        return (
          <div key={show.id}>
            {leg && (
              <div
                className={leg.severity === 'fine' ? 'statusbar' : 'note'}
                data-testid={`leg-${index}`}
              >
                ↳ {Math.round(leg.miles)} mi
                {leg.nights > 0 && ` over ${leg.nights} night${leg.nights === 1 ? '' : 's'}`}
                {leg.severity === 'long' && ' — a long way between shows'}
                {leg.severity === 'implausible' &&
                  ' — that is not a drive, that is a flight'}
              </div>
            )}
            <div className="card">
              <div className="show">
                <div className="when">{prettyDate(show.date)}</div>
                <div className="body">
                  <div className="artist">{show.artist}</div>
                  <div className="where">{show.city ?? show.country ?? ''}</div>
                </div>
                <button type="button" className="danger" onClick={() => onRemove(show)}>
                  remove
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
