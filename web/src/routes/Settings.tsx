import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { GeocodeResult, SettingSpec, SettingsPayload } from '../lib/types'

const THRESHOLD_STOPS = [
  { value: 0.2, label: 'everything' },
  { value: 0.35, label: 'worth a look' },
  { value: 0.5, label: 'worth a drive' },
  { value: 0.75, label: 'only the good ones' },
]

export function Settings() {
  const [payload, setPayload] = useState<SettingsPayload | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GeocodeResult[]>([])

  useEffect(() => {
    api.settings().then(setPayload).catch((err) => setError(String(err)))
  }, [])

  async function save(key: string, value: unknown) {
    setError(null)
    try {
      await api.updateSettings({ [key]: value })
      setPayload(await api.settings())
      setMessage('Saved — takes effect on the next scan, no restart needed.')
    } catch (err) {
      setError(String((err as Error).message ?? err))
    }
  }

  async function search(event: React.FormEvent) {
    event.preventDefault()
    setResults((await api.geocode(query)).results)
  }

  async function chooseHome(result: GeocodeResult) {
    await api.setHome({ lat: result.lat, lon: result.lon, label: result.label })
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

  const hidden = new Set(['home_lat', 'home_lon', 'home_label', 'notify_min_score'])
  const rest = payload.settings.filter((s) => !hidden.has(s.key))

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
            {Number(byKey('home_lon')?.value).toFixed(4)})
          </span>
        </div>
        <form className="row" onSubmit={search}>
          <input
            type="search"
            placeholder="Search for a place…"
            aria-label="Search for a place"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ flex: 1 }}
          />
          <button type="submit" disabled={!payload.credentials.openrouteservice}>
            Search
          </button>
        </form>
        {!payload.credentials.openrouteservice && (
          <div className="muted" style={{ fontSize: 13 }}>
            OpenRouteService isn't configured, so search is unavailable — set
            home by editing the coordinates below.
          </div>
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
      <div className="card stack">
        <label htmlFor="threshold">
          Alert threshold — {threshold.toFixed(2)}
        </label>
        <input
          id="threshold"
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={threshold}
          onChange={(e) => save('notify_min_score', Number(e.target.value))}
        />
        <div className="row">
          {THRESHOLD_STOPS.map((stop) => (
            <button
              key={stop.value}
              type="button"
              className={threshold === stop.value ? 'primary' : undefined}
              onClick={() => save('notify_min_score', stop.value)}
            >
              {stop.label}
            </button>
          ))}
        </div>
        <div className="muted" style={{ fontSize: 13 }}>
          Health alerts go to a separate topic and are never muted by this.
        </div>
      </div>

      <h2>Behaviour</h2>
      {rest.map((spec) => (
        <SettingRow key={spec.key} spec={spec} onSave={save} />
      ))}

      <h2>Credentials</h2>
      <div className="card">
        <p className="muted" style={{ marginTop: 0, fontSize: 14 }}>
          Keys live in the env file and are never shown or editable here —
          changing one is a deploy, which is the right amount of friction for
          something that grants access.
        </p>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Usage</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(payload.credentials).map(([name, present]) => {
              const quota = payload.quotas.find((q) => q.provider === name)
              return (
                <tr key={name}>
                  <td>{name}</td>
                  <td className={present ? undefined : 'muted'}>
                    {present ? 'configured' : 'not configured'}
                  </td>
                  <td className="muted">
                    {quota
                      ? `${quota.used}/${quota.cap} this ${quota.period === 'monthly' ? 'month' : 'day'}`
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function SettingRow({
  spec,
  onSave,
}: {
  spec: SettingSpec
  onSave: (key: string, value: unknown) => void
}) {
  const [value, setValue] = useState(spec.value)

  if (spec.kind === 'bool') {
    return (
      <div className="card">
        <label style={{ display: 'flex', gap: 10, alignItems: 'center', margin: 0 }}>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(e) => {
              setValue(e.target.checked)
              onSave(spec.key, e.target.checked)
            }}
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
      <div className="row">
        <input
          id={spec.key}
          type={spec.kind === 'date' ? 'text' : spec.kind === 'str' ? 'text' : 'number'}
          value={String(value)}
          min={spec.minimum ?? undefined}
          max={spec.maximum ?? undefined}
          step={spec.kind === 'float' ? 0.05 : 1}
          onChange={(e) => setValue(e.target.value)}
          style={{ flex: 1 }}
        />
        <button
          type="button"
          onClick={() => onSave(spec.key, value)}
          disabled={String(value) === String(spec.value)}
        >
          Save
        </button>
      </div>
      {spec.help && (
        <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
          {spec.help}
        </div>
      )}
    </div>
  )
}
