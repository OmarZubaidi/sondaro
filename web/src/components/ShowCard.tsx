import type { Show } from '../lib/types'
import { driveTime, isWeekend, place, prettyDate } from '../lib/format'
import { FlagChip } from './FlagChip'
import { ScoreBar } from './ScoreBar'

interface Props {
  show: Show
  selected?: boolean
  onToggle?: (show: Show) => void
  showDate?: boolean
}

export function ShowCard({ show, selected = false, onToggle, showDate = true }: Props) {
  const drive = driveTime(show)
  const weekend = isWeekend(show.date)
  const interactive = Boolean(onToggle)

  const body = (
    <>
      {showDate && (
        <div className="when">
          <span className={weekend ? 'weekend' : undefined}>{prettyDate(show.date)}</span>
          {show.time && (
            <>
              <br />
              <span className="muted">{show.time}</span>
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
            {show.miles !== null && <span className="muted"> · {Math.round(show.miles)} mi</span>}
          </div>
        )}
        <div className="chips">
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
    <div className={`card${selected ? ' selected' : ''}`}>
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
      {show.url && (
        <div style={{ marginTop: 8 }}>
          <a href={show.url} target="_blank" rel="noreferrer">
            tickets ↗
          </a>
        </div>
      )}
    </div>
  )
}
