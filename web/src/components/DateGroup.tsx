import type { Show } from '../lib/types'
import { isWeekend } from '../lib/format'
import { ShowCard } from './ShowCard'

interface Props {
  date: string
  shows: Show[]
  onChanged?: () => void
}

/** Every option for a night is listed, highest scoring first. Nothing is
 *  hidden and nothing is chosen — picking is the user's job. */
export function DateGroup({ date, shows, onChanged }: Props) {
  const ordered = [...shows].sort((a, b) => b.score - a.score)

  return (
    <section>
      <h2>
        {/* the heading is the date and nothing else; a Friday still reads
            differently, which is the part of the weekday that changes a plan */}
        <span className={isWeekend(date) ? 'weekend' : undefined}>{date}</span>
        {ordered.length > 1 && (
          <span className="muted"> · {ordered.length} options</span>
        )}
      </h2>
      {ordered.map((show) => (
        <ShowCard key={show.id} show={show} showDate={false} onChanged={onChanged} />
      ))}
    </section>
  )
}
