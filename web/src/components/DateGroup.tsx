import type { Show } from '../lib/types'
import { prettyDateLong } from '../lib/format'
import { ShowCard } from './ShowCard'

interface Props {
  date: string
  shows: Show[]
  selectedId?: string | null
  onToggle?: (show: Show) => void
}

/** Every option for a night is listed, highest scoring first. Nothing is
 *  hidden and nothing is chosen — picking is the user's job. */
export function DateGroup({ date, shows, selectedId, onToggle }: Props) {
  const ordered = [...shows].sort((a, b) => b.score - a.score)

  return (
    <section>
      <h2>
        {prettyDateLong(date)}
        {ordered.length > 1 && (
          <span className="muted"> · {ordered.length} options</span>
        )}
      </h2>
      {ordered.map((show) => (
        <ShowCard
          key={show.id}
          show={show}
          showDate={false}
          selected={selectedId === show.id}
          onToggle={onToggle}
        />
      ))}
    </section>
  )
}
