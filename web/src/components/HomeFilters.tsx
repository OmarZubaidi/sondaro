export interface Filters {
  weeknight_hours: number
  sunday_hours: number
  weekend_hours: number
  min_score: number
}

interface Props {
  value: Filters
  onChange: (next: Filters) => void
}

/** Live filters. These re-score events already in the database, so changing a
 *  control never costs an API call — nothing is refetched. Drive budgets are
 *  one-way: the time it takes to get there, not the round trip.
 *
 *  Deliberately a number field rather than a slider: every drag position was a
 *  round trip, which stuttered between stops. */
export function HomeFilters({ value, onChange }: Props) {
  const set = <K extends keyof Filters>(key: K, next: number) =>
    onChange({ ...value, [key]: next })

  return (
    <div className="card filters">
      <div className="grid3">
        <HourField
          id="f-weeknight"
          label="Mon–Thu"
          value={value.weeknight_hours}
          onChange={(v) => set('weeknight_hours', v)}
        />
        <HourField
          id="f-sunday"
          label="Sunday"
          value={value.sunday_hours}
          onChange={(v) => set('sunday_hours', v)}
        />
        <HourField
          id="f-weekend"
          label="Fri–Sat"
          value={value.weekend_hours}
          onChange={(v) => set('weekend_hours', v)}
        />
      </div>
      <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
        Hours you'd drive each way for an artist you love.
      </div>

      <div className="inline-field" style={{ marginTop: 14 }}>
        <label htmlFor="f-min">Hide anything below</label>
        <input
          id="f-min"
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={value.min_score}
          onChange={(e) =>
            set('min_score', Math.min(1, Math.max(0, Number(e.target.value) || 0)))
          }
        />
      </div>
    </div>
  )
}

function HourField({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: number
  onChange: (value: number) => void
}) {
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={0.5}
        max={24}
        step={0.5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  )
}
