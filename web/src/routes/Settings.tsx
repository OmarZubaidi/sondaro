import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { GeocodeResult, SettingSpec, SettingsPayload } from '../lib/types'

const THRESHOLD_STOPS = [
  { value: 0.2, label: 'everything' },
  { value: 0.35, label: 'worth a look' },
  { value: 0.5, label: 'worth a drive' },
  { value: 0.75, label: 'only the good ones' },
]

// these live on the Near home page as live filters instead, where you can see
// what they do while you move them
const ON_HOME_PAGE = new Set([
  'base_hours_weeknight',
  'base_hours_sunday',
  'base_hours_weekend',
  'min_score',
])

const clamp = (value: number) => Math.min(1, Math.max(0, value || 0))

const HANDLED_SEPARATELY = new Set(['home_lat', 'home_lon', 'home_label', 'notify_min_score'])

export function Settings() {
  const [payload, setPayload] = useState<SettingsPayload | null>(null)
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GeocodeResult[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.settings().then(setPayload).catch((err) => setError(String(err)))
  }, [])

  async function persist(changes: Record<string, unknown>, note: string) {
    setError(null)
    try {
      await api.updateSettings(changes)
      setPayload(await api.settings())
      setDraft({})
      setMessage(note)
    } catch (err) {
      setError(String((err as Error).message ?? err))
    }
  }

  async function saveAll() {
    setSaving(true)
    try {
      await persist(draft, 'Saved. Takes effect on the next scan, no restart needed.')
    } finally {
      setSaving(false)
    }
  }

  async function search(event: React.FormEvent) {
    event.preventDefault()
    setResults((await api.geocode(query)).results)
  }

  async function chooseHome(result: GeocodeResult) {
    await api.setHome({
      lat: result.lat,
      lon: result.lon,
      label: result.label,
      country: result.country ?? undefined,
    })
    setResults([])
    setQuery('')
    setPayload(await api.settings())
    setMessage(
      'Home moved. Drive times are keyed on origin so they re-resolve for the ' +
        'new place, and coverage is being rebuilt.',
    )
  }

  if (error && !payload) return <div className="note">{error}</div>
  if (!payload) return <div className="empty">Loading…</div>

  const byKey = (key: string) => payload.settings.find((s) => s.key === key)
  const threshold = Number(byKey('notify_min_score')?.value ?? 0.35)
  const editable = payload.settings.filter(
    (s) => !ON_HOME_PAGE.has(s.key) && !HANDLED_SEPARATELY.has(s.key),
  )
  const dirty = Object.keys(draft).length > 0

  return (
    <>
      {message && <div className="progress">{message}</div>}
      {error && <div className="note">{error}</div>}

      <h2>Home</h2>
      <div className="card stack">
        <div>
          Currently <strong>{String(byKey('home_label')?.value ?? '')}</strong>{' '}
          <span className="muted">
            ({Number(byKey('home_lat')?.value).toFixed(4)},{' '}
            {Number(byKey('home_lon')?.value).toFixed(4)}
            {byKey('home_country')?.value ? `, ${byKey('home_country')?.value}` : ''})
          </span>
        </div>
        {payload.home_managed_by ? (
          <div className="muted" style={{ fontSize: 14 }}>
            Kept in sync from {payload.home_managed_by}, so there's one place to
            change it. Update it there and it lands here on the next sync.
          </div>
        ) : (
        <>
          <form className="row" onSubmit={search}>
            <input
              type="search"
              placeholder="Search for a place…"
              aria-label="Search for a place"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ flex: 1 }}
            />
            <button type="submit">Search</button>
          </form>
        </>
        )}
        {results.map((result) => (
          <button
            key={`${result.lat},${result.lon}`}
            type="button"
            onClick={() => chooseHome(result)}
          >
            {result.label}
          </button>
        ))}
      </div>

      <h2>Alerts</h2>
      <div className="card">
        <div className="inline-field">
          <label htmlFor="threshold">Alert above</label>
          <input
            id="threshold"
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={threshold}
            onChange={(e) =>
              persist({ notify_min_score: clamp(Number(e.target.value)) }, 'Threshold updated.')
            }
          />
          <div className="segmented">
            {THRESHOLD_STOPS.map((stop) => (
              <button
                key={stop.value}
                type="button"
                aria-pressed={threshold === stop.value}
                onClick={() => persist({ notify_min_score: stop.value }, 'Threshold updated.')}
              >
                {stop.label}
              </button>
            ))}
          </div>
        </div>
        <div className="muted" style={{ fontSize: 13, marginTop: 8 }}>
          Health alerts use a separate topic and are never muted by this.
        </div>
      </div>

      <h2>Behaviour</h2>
      {editable.map((spec) => (
        <SettingRow
          key={spec.key}
          spec={spec}
          value={draft[spec.key] ?? spec.value}
          onChange={(value) => setDraft((d) => ({ ...d, [spec.key]: value }))}
        />
      ))}

      <div className="row">
        <button className="primary" type="button" onClick={saveAll} disabled={!dirty || saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {dirty && (
          <button type="button" onClick={() => setDraft({})}>
            Discard
          </button>
        )}
      </div>
    </>
  )
}

function SettingRow({
  spec,
  value,
  onChange,
}: {
  spec: SettingSpec
  value: string | number | boolean
  onChange: (value: string | number | boolean) => void
}) {
  if (spec.kind === 'bool') {
    return (
      <div className="card">
        <label style={{ display: 'flex', gap: 10, alignItems: 'center', margin: 0 }}>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span style={{ color: 'var(--text)' }}>{spec.label}</span>
        </label>
        {spec.help && (
          <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
            {spec.help}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="card">
      <label htmlFor={spec.key}>{spec.label}</label>
      <input
        id={spec.key}
        type={spec.kind === 'float' || spec.kind === 'int' ? 'number' : 'text'}
        value={String(value)}
        min={spec.minimum ?? undefined}
        max={spec.maximum ?? undefined}
        step={spec.kind === 'float' ? 0.05 : 1}
        onChange={(e) => onChange(e.target.value)}
      />
      {spec.help && (
        <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
          {spec.help}
        </div>
      )}
    </div>
  )
}
