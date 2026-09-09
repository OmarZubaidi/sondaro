import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { SettingSpec, SettingsPayload } from '../lib/types'
import { CalendarSubscription } from '../components/CalendarSubscription'

const THRESHOLD_STOPS = [
  { value: 0.2, label: 'everything' },
  { value: 0.35, label: 'worth a look' },
  { value: 0.5, label: 'worth a drive' },
  { value: 0.75, label: 'only the good ones' },
]

// these live as live controls on the page they affect, where you can see what
// they do while you move them
const ON_LOCAL_PAGE = new Set([
  'base_hours_weeknight',
  'base_hours_sunday',
  'base_hours_weekend',
  'min_score',
  'cluster_days',
  'cluster_km',
])

const clamp = (value: number) => Math.min(1, Math.max(0, value || 0))

// where you live comes from Home Assistant, timezone included. There is
// nothing to edit here that wouldn't be overwritten on the next sync.
const FROM_HOME_ASSISTANT = new Set([
  'home_lat',
  'home_lon',
  'home_label',
  'home_country',
  'home_tz',
])

// Everything about alerts, under the one heading. They were split across two
// sections purely by how they're drawn: the threshold needs a hand-built
// control, so it was lifted out and the other two were left behind in the
// generic list at the bottom, a screen away from the thing they qualify.
const ALERTS = ['notify_min_score', 'notify_max_per_run', 'mute_until']
const HANDLED_SEPARATELY = new Set(ALERTS)

export function Settings() {
  const [payload, setPayload] = useState<SettingsPayload | null>(null)
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.settings().then(setPayload).catch((err) => setError(String(err)))
  }, [])

  async function saveAll() {
    setSaving(true)
    setError(null)
    try {
      await api.updateSettings(draft)
      setPayload(await api.settings())
      setDraft({})
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setSaving(false)
    }
  }

  if (error && !payload) return <div className="note">{error}</div>
  if (!payload) return <div className="empty">Loading…</div>

  const byKey = (key: string) => payload.settings.find((s) => s.key === key)
  const edit = (key: string, value: string | number | boolean) =>
    setDraft((d) => ({ ...d, [key]: value }))

  // the draft wins while it exists, so a control shows what you typed rather
  // than what's stored
  const threshold = Number(draft.notify_min_score ?? byKey('notify_min_score')?.value ?? 0.35)
  const editable = payload.settings.filter(
    (s) =>
      !ON_LOCAL_PAGE.has(s.key) &&
      !HANDLED_SEPARATELY.has(s.key) &&
      !FROM_HOME_ASSISTANT.has(s.key),
  )
  const dirty = Object.keys(draft).length > 0

  return (
    <>
      {error && <div className="note">{error}</div>}

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
            onChange={(e) => edit('notify_min_score', clamp(Number(e.target.value)))}
          />
          <div className="segmented">
            {THRESHOLD_STOPS.map((stop) => (
              <button
                key={stop.value}
                type="button"
                aria-pressed={threshold === stop.value}
                onClick={() => edit('notify_min_score', stop.value)}
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

      {/* the threshold is the headline; how many and until when qualify it */}
      {ALERTS.slice(1).map((key) => {
        const spec = byKey(key)
        return spec ? (
          <SettingRow
            key={key}
            spec={spec}
            value={draft[key] ?? spec.value}
            onChange={(value) => edit(key, value)}
          />
        ) : null
      })}

      <h2>Calendar</h2>
      <CalendarSubscription tailnetUrl={payload.tailnet_url} />

      <h2>Behaviour</h2>
      {editable.map((spec) => (
        <SettingRow
          key={spec.key}
          spec={spec}
          value={draft[spec.key] ?? spec.value}
          onChange={(value) => edit(spec.key, value)}
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
