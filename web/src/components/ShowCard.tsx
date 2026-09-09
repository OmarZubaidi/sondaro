import type { Show } from '../lib/types'
import { driveTime, isWeekend, place, timeRange } from '../lib/format'
import { FlagChip } from './FlagChip'
import { ScoreBar } from './ScoreBar'
import { TicketToggle, useTicket } from './TicketToggle'

interface Props {
  show: Show
  selected?: boolean
  onToggle?: (show: Show) => void
  showDate?: boolean
  /** Off when the list is already grouped by act, which promotes the venue to
   *  the card's lead line — there's nothing else for it to be about. */
  showArtist?: boolean
  /** Off where the score says the same thing on every card in the group: the
   *  favorites feed has no geography to score, so it's the artist's affinity and
   *  belongs in the heading once. */
  showScore?: boolean
  /** Off when the list is already grouped by country. */
  showCountry?: boolean
  /** Spelled-out country, on its own line under the venue. A code tacked onto
   *  the end of a place line is noise; on a worldwide list the country is the
   *  thing you're scanning for. */
  countryName?: string
  /** Called after the ticket state changes, so the list can re-filter. */
  onChanged?: () => void
}

export function ShowCard({
  show,
  selected = false,
  onToggle,
  showDate = true,
  showArtist = true,
  showScore = true,
  showCountry = true,
  countryName,
  onChanged,
}: Props) {
  const where = place(show, { country: showCountry }) || 'venue to be announced'
  const drive = driveTime(show)
  const hours = timeRange(show)
  const weekend = isWeekend(show.date)
  const interactive = Boolean(onToggle)
  const { bought, pending, toggle } = useTicket(show, onChanged)
  const hasChips =
    bought ||
    Boolean(show.trips?.length) ||
    show.reasons.length > 0 ||
    show.flags.length > 0

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
        {showArtist ? (
          <>
            <div className="lead">{show.artist}</div>
            <div className="where">{where}</div>
          </>
        ) : (
          <div className="lead">{where}</div>
        )}
        {countryName && <div className="where">{countryName}</div>}
        {drive && (
          <div className="drive">
            {drive} drive
            {show.km !== null && <span className="muted"> · {Math.round(show.km)} km</span>}
          </div>
        )}
        {/* the row carries its own top margin, so an empty one is a gap */}
        {hasChips && (
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
        )}
      </div>
      {showScore && <ScoreBar score={show.score} />}
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
        <TicketToggle bought={bought} pending={pending} onToggle={toggle} />
      </div>
    </div>
  )
}
