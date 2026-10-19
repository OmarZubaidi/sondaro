interface Option {
  value: string
  label: string
  /** a string lets a row say something other than a number — "…" for a count
   *  that isn't final yet */
  count?: number | string
  /** hover text, for whatever the count can't say on its own */
  hint?: string
}

interface Props {
  legend: string
  options: Option[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
}

/** A small multi-select filter. Nothing ticked means no filter rather than no
 *  results — an empty page you have to fix is a worse default than everything. */
export function CheckList({ legend, options, selected, onChange }: Props) {
  if (options.length === 0) return null

  const toggle = (value: string) => {
    const next = new Set(selected)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    onChange(next)
  }

  return (
    <fieldset className="checklist">
      <legend>
        <span className="tag">{legend}</span>
        {selected.size > 0 && (
          <button type="button" className="linkish" onClick={() => onChange(new Set())}>
            clear
          </button>
        )}
      </legend>
      {options.map((option) => (
        <label key={option.value} title={option.hint}>
          <input
            type="checkbox"
            checked={selected.has(option.value)}
            onChange={() => toggle(option.value)}
          />
          <span>{option.label}</span>
          {option.count !== undefined && <em>{option.count}</em>}
        </label>
      ))}
    </fieldset>
  )
}
