import { useEffect, useId, useRef, useState } from 'react'

export interface Choice {
  value: string
  label: string
  hint?: string
}

interface Props {
  label: string
  help?: string
  placeholder?: string
  selected: Choice[]
  /** Static list to filter as you type. Omit when `search` supplies them. */
  options?: Choice[]
  /** Async lookup, for lists too big to hold — cities. Debounced. */
  search?: (query: string) => Promise<Choice[]>
  onChange: (next: Choice[]) => void
  disabled?: boolean
}

const DEBOUNCE_MS = 350

/** Pick several things from a list, shown as chips.
 *
 *  Never accepts what you typed as a value, only what you picked. A trip built
 *  from free text can hold a country that doesn't exist or a misspelled city,
 *  and both fail silently much later — as a leg that quietly matches nothing.
 */
export function ChipSelect({
  label,
  help,
  placeholder,
  selected,
  options,
  search,
  onChange,
  disabled = false,
}: Props) {
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<Choice[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const listId = useId()
  const box = useRef<HTMLDivElement>(null)

  const chosen = new Set(selected.map((s) => s.value))

  // static list: filter locally, no waiting
  const local =
    options && query.trim()
      ? options
          .filter((o) => !chosen.has(o.value))
          .filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
          .slice(0, 8)
      : []

  useEffect(() => {
    if (!search || query.trim().length < 2) {
      setFound([])
      return
    }
    let cancelled = false
    setBusy(true)
    // debounced: every keystroke is a geocoder call, and that's a daily quota
    const timer = setTimeout(() => {
      search(query.trim())
        .then((results) => !cancelled && setFound(results))
        .catch(() => !cancelled && setFound([]))
        .finally(() => !cancelled && setBusy(false))
    }, DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, search])

  useEffect(() => {
    const away = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  const suggestions = (options ? local : found.filter((o) => !chosen.has(o.value))).slice(0, 8)

  function add(choice: Choice) {
    onChange([...selected, choice])
    setQuery('')
    setFound([])
    setOpen(false)
  }

  function remove(value: string) {
    onChange(selected.filter((s) => s.value !== value))
  }

  return (
    <div className="chip-select" ref={box}>
      <label htmlFor={listId}>{label}</label>

      <div className={`chip-field${disabled ? ' disabled' : ''}`}>
        {selected.map((choice) => (
          <span className="chip picked" key={choice.value}>
            {choice.label}
            <button
              type="button"
              aria-label={`Remove ${choice.label}`}
              onClick={() => remove(choice.value)}
              disabled={disabled}
            >
              ×
            </button>
          </span>
        ))}
        <input
          id={listId}
          type="text"
          autoComplete="off"
          placeholder={selected.length ? '' : placeholder}
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            // typing is never a value: Enter takes the top suggestion or does
            // nothing, and Backspace on an empty box removes the last chip
            if (e.key === 'Enter') {
              e.preventDefault()
              if (suggestions[0]) add(suggestions[0])
            }
            if (e.key === 'Backspace' && !query && selected.length) {
              remove(selected[selected.length - 1].value)
            }
          }}
        />
      </div>

      {open && query.trim().length > 0 && (
        <ul className="chip-options">
          {suggestions.map((choice) => (
            <li key={choice.value}>
              <button type="button" onClick={() => add(choice)}>
                {choice.label}
                {choice.hint && <span className="muted"> {choice.hint}</span>}
              </button>
            </li>
          ))}
          {suggestions.length === 0 && (
            <li className="muted empty-option">
              {busy ? 'Searching…' : query.trim().length < 2 ? 'Keep typing…' : 'Nothing matches'}
            </li>
          )}
        </ul>
      )}

      {help && <div className="field-help muted">{help}</div>}
    </div>
  )
}
