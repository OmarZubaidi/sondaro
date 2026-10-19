import type { Show } from '../lib/types'
import { dayNumber, driveTime, monthYear, place, weekdayLong } from '../lib/format'

interface Props {
  show: Show
}

/** The next show you've bought a ticket for, above everything you haven't. */
export function NextUp({ show }: Props) {
  const drive = driveTime(show)
  const where = [
    place(show) || 'venue to be announced',
    drive && `${drive} drive`,
    show.km !== null && `${Math.round(show.km)} km`,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <section className="next-up" aria-label="Next up">
      <div className="next-up-act">
        <div className="next-up-dots" aria-hidden="true" />
        <span className="next-up-label">Next up · ✓ going</span>
        <div className="next-up-name">
          <span className="next-up-sticker">{show.artist}</span>
          <span className="next-up-where">{where}</span>
        </div>
      </div>
      <div className="next-up-when">
        <span className="next-up-weekday">
          {[weekdayLong(show.date), show.time].filter(Boolean).join(' · ')}
        </span>
        <span className="next-up-day">{dayNumber(show.date)}</span>
        <span className="next-up-month">{monthYear(show.date)}</span>
      </div>
    </section>
  )
}
