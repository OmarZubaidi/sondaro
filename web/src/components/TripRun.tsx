import type { Show } from '../lib/types'
import { place } from '../lib/format'
import { TicketToggle, useTicket } from './TicketToggle'

interface Props {
  artist: string
  shows: Show[]
  onChanged?: () => void
}

/** One artist's consecutive dates inside a trip.
 *
 *  Every run is headed and framed, including a run of one: a lone date with
 *  its act inline read as a different kind of thing sitting among the blocks,
 *  when it's the same kind of thing with one date in it. The same act
 *  appearing either side of another one is two runs, not one, because the gap
 *  between them is a gap you'd have to fill.
 *
 *  Rows rather than cards, because a trip is read as a schedule — and the
 *  schedule is short enough that a heading saying how long it is only repeats
 *  what's under it.
 */
export function TripRun({ artist, shows, onChanged }: Props) {
  return (
    <div className="run">
      {/* the rows below are the count */}
      <div className="run-head">
        <strong>{artist}</strong>
      </div>
      {shows.map((show) => (
        <TripDate key={show.id} show={show} onChanged={onChanged} />
      ))}
    </div>
  )
}

function TripDate({ show, onChanged }: { show: Show; onChanged?: () => void }) {
  const { bought, pending, toggle } = useTicket(show, onChanged)

  return (
    <div className={`trip-date${bought ? ' held' : ''}`}>
      <span className="on">{show.date}</span>
      <span className="at">{show.time ?? ''}</span>
      {/* the run names the act and the rows carry the region, so the country
          code would only repeat what's above and beside it */}
      <span className="what">{place(show, { country: false }) || 'venue to be announced'}</span>
      {show.url ? (
        <a href={show.url} target="_blank" rel="noreferrer" aria-label="tickets">
          tickets ↗
        </a>
      ) : (
        <span />
      )}
      <TicketToggle bought={bought} pending={pending} onToggle={toggle} terse />
    </div>
  )
}
