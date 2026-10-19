import type { Show } from '../lib/types'
import { dateLabel } from '../lib/format'
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
    <section className="date-group">
      <h3 className="date-tag">
        <span className="date-label">{dateLabel(date)}</span>
        {ordered.length > 1 && <span>· {ordered.length} options</span>}
      </h3>
      {ordered.map((show) => (
        <ShowCard key={show.id} show={show} showDate={false} onChanged={onChanged} />
      ))}
    </section>
  )
}
