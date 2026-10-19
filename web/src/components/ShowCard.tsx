import type { Show } from '../lib/types'
import {
  dayNumber,
  driveTime,
  isWeekend,
  monthYear,
  place,
  placeParts,
  weekdayShort,
} from '../lib/format'
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
  /** One act's dates: the date on one line, the town over the venue, and the
   *  country in a column of its own. */
  compact?: boolean
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
  compact = false,
  onChanged,
}: Props) {
  const where = place(show, { country: showCountry }) || 'venue to be announced'
  const parts = placeParts(show, { country: showCountry })
  const drive = driveTime(show)
  const { bought, pending, toggle } = useTicket(show, onChanged)
  const hasChips =
    bought ||
    Boolean(show.trips?.length) ||
    show.reasons.length > 0 ||
    show.flags.length > 0

  const weekday = (
    <span className={`dow${isWeekend(show.date) ? ' weekend' : ''}`}>
      {weekdayShort(show.date)}
    </span>
  )
  const time = show.time && <span className="time">{show.time}</span>

  const body = (
    <>
      {showDate &&
        (compact ? (
          <div className="when">
            <span className="day">{dayNumber(show.date)}</span>
            <span className="month">{monthYear(show.date)}</span>
            {weekday}
            {time}
          </div>
        ) : (
          <div className="when">
            <div className="when-day">
              <span className="day">{dayNumber(show.date)}</span>
              {weekday}
            </div>
            {time}
          </div>
        ))}
      <div className="body">
        {compact ? (
          <>
            <div className="lead">{parts.title}</div>
            {parts.sub && <div className="where">{parts.sub}</div>}
          </>
        ) : showArtist ? (
          <>
            <div className="lead">{show.artist}</div>
            <div className="where">{where}</div>
          </>
        ) : (
          <div className="lead">{where}</div>
        )}
        {countryName && !compact && <div className="where">{countryName}</div>}
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
      {countryName && compact && <div className="country">{countryName}</div>}
      {(drive || showScore) && (
        <div className="reach">
          {drive && (
            <span className="drive">
              {drive} drive
              {show.km !== null && <span className="muted"> · {Math.round(show.km)} km</span>}
            </span>
          )}
          {showScore && <ScoreBar score={show.score} />}
        </div>
      )}
    </>
  )

  const className = `show-row${compact ? ' compact' : ''}${selected ? ' selected' : ''}${bought ? ' held' : ''}`

  return (
    <article className={className}>
      {onToggle ? (
        <button
          type="button"
          className="show"
          aria-pressed={selected}
          onClick={() => onToggle(show)}
        >
          {body}
        </button>
      ) : (
        <div className="show">{body}</div>
      )}
      <div className="actions">
        {show.url && (
          <a className="tickets" href={show.url} target="_blank" rel="noreferrer">
            tickets ↗
          </a>
        )}
        <TicketToggle bought={bought} pending={pending} onToggle={toggle} />
      </div>
    </article>
  )
}
