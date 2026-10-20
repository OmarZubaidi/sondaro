import { useState } from 'react'

interface Props {
  id: string
  min: number
  max: number
  step?: number
  value: number
  onChange: (value: number) => void
}

/** A number box clamped to its range. Anything under the floor is held as typed
 *  rather than snapped up to it, so 250 can be cleared to type 500, and is
 *  dropped for the last good value when the box loses focus. */
export function NumberField({ id, min, max, step = 1, value, onChange }: Props) {
  const [draft, setDraft] = useState<string | null>(null)

  return (
    <input
      id={id}
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft ?? value}
      onChange={(e) => {
        const typed = Number(e.target.value)
        if (e.target.value === '' || typed < min) {
          setDraft(e.target.value)
          return
        }
        setDraft(null)
        onChange(Math.min(max, typed))
      }}
      onBlur={() => setDraft(null)}
    />
  )
}
