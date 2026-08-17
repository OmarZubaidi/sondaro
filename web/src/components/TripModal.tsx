import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Trip, TripLeg } from '../lib/types'
import { ChipSelect, type Choice } from './ChipSelect'

interface Props {
  trip?: Trip
  countries: { code: string; name: string }[]
  onClose: () => void
  onSaved: () => void
}

interface Draft {
  name: string
  start_date: string
  end_date: string
  strict_dates: boolean
  flex_before: number
  flex_after: number
  countries: Choice[]
  legs: TripLeg[]
}

const blank = (): Draft => ({
  name: '',
  start_date: '',
  end_date: '',
  strict_dates: false,
  flex_before: 3,
  flex_after: 3,
  countries: [],
  legs: [],
})

function fromTrip(trip: Trip, names: Map<string, string>): Draft {
  return {
    name: trip.name,
    start_date: trip.start_date,
    end_date: trip.end_date,
    strict_dates: trip.strict_dates,
    flex_before: trip.flex_before,
    flex_after: trip.flex_after,
    countries: trip.countries.map((code) => ({
      value: code,
      label: names.get(code) ?? code,
    })),
    legs: trip.legs.filter((leg) => leg.city),
  }
}

/** Create or edit a trip.
 *
 *  Shaped around how a trip actually gets planned: you know the countries
 *  first, the cities as they're booked, and the dates for each city last. So
 *  countries come first and cities are optional, and a country you've named no
 *  city in stays deliberately open — that's what keeps a show just over its
 *  border in play.
 */
export function TripModal({ trip, countries, onClose, onSaved }: Props) {
  const names = useMemo(
    () => new Map(countries.map((c) => [c.code, c.name])),
    [countries],
  )
  const [draft, setDraft] = useState<Draft>(() => (trip ? fromTrip(trip, names) : blank()))
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const picked = draft.countries.map((c) => c.value)

  // dropping a country has to drop the cities inside it, or the trip keeps a
  // leg for somewhere it's no longer going
  const cityChoices: Choice[] = draft.legs
    .filter((leg) => picked.includes(leg.country))
    .map((leg) => ({
      value: `${leg.country}:${leg.city}`,
      label: leg.city as string,
    }))

  function setCities(next: Choice[]) {
    const keys = new Set(next.map((c) => c.value))
    const kept = draft.legs.filter((leg) => keys.has(`${leg.country}:${leg.city}`))
    const added = next
      .filter((c) => !draft.legs.some((leg) => `${leg.country}:${leg.city}` === c.value))
      .map((c) => {
        const [country, city] = c.value.split(':')
        return { country, city, start_date: null, end_date: null } as TripLeg
      })
    set('legs', [...kept, ...added])
  }

  function setLegDates(index: number, field: 'start_date' | 'end_date', value: string) {
    set(
      'legs',
      draft.legs.map((leg, i) => (i === index ? { ...leg, [field]: value || null } : leg)),
    )
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)

    // a country with cities contributes those cities; one without contributes
    // itself, unplanned and wide open
    const withCities = new Set(draft.legs.map((leg) => leg.country))
    const legs: TripLeg[] = [
      ...draft.legs.filter((leg) => picked.includes(leg.country)),
      ...picked
        .filter((code) => !withCities.has(code))
        .map((country) => ({ country, city: null, start_date: null, end_date: null })),
    ]

    const payload = {
      name: draft.name,
      start_date: draft.start_date,
      end_date: draft.end_date,
      strict_dates: draft.strict_dates,
      flex_before: draft.flex_before,
      flex_after: draft.flex_after,
      legs,
    }

    try {
      if (trip) await api.updateTrip(trip.id, payload)
      else await api.createTrip(payload)
      onSaved()
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="scrim shown" onClick={onClose} aria-hidden="true" />
      <div className="modal" role="dialog" aria-modal="true" aria-label={trip ? 'Edit trip' : 'New trip'}>
        <form className="modal-inner" onSubmit={submit}>
          <div className="modal-head">
            <h2>{trip ? 'Edit trip' : 'New trip'}</h2>
            <button type="button" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>

          <div className="modal-body stack">
            {error && <div className="note">{error}</div>}

            <div>
              <label htmlFor="trip-name">Name</label>
              <input
                id="trip-name"
                type="text"
                required
                autoFocus
                placeholder="Summer in Europe"
                value={draft.name}
                onChange={(e) => set('name', e.target.value)}
              />
            </div>

            <div className="grid2">
              <div>
                <label htmlFor="trip-start">First day</label>
                <input
                  id="trip-start"
                  type="date"
                  required
                  value={draft.start_date}
                  onChange={(e) => set('start_date', e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="trip-end">Last day</label>
                <input
                  id="trip-end"
                  type="date"
                  required
                  min={draft.start_date || undefined}
                  value={draft.end_date}
                  onChange={(e) => set('end_date', e.target.value)}
                />
              </div>
            </div>

            <ChipSelect
              label="Countries"
              placeholder="Start typing — United, Fra…"
              help="A country you name no city in stays wide open, so a show just over its border still counts."
              options={countries.map((c) => ({ value: c.code, label: c.name, hint: c.code }))}
              selected={draft.countries}
              onChange={(next) => {
                const keep = new Set(next.map((c) => c.value))
                set('countries', next)
                set('legs', draft.legs.filter((leg) => keep.has(leg.country)))
              }}
            />

            <ChipSelect
              label="Cities (optional)"
              placeholder={picked.length ? 'Add a city you’ve booked…' : 'Pick a country first'}
              help="Only cities inside the countries above. Naming one narrows that country and leaves the others alone."
              disabled={picked.length === 0}
              selected={cityChoices}
              search={async (q) => {
                const { cities } = await api.cities(q, picked)
                return cities.map((city) => ({
                  value: `${city.country}:${city.name}`,
                  label: city.name,
                  hint: city.label.split(',').slice(1).join(',').trim(),
                }))
              }}
              onChange={setCities}
            />

            {draft.legs.length > 0 && (
              <div className="legs">
                <div className="muted field-help">
                  When you're where. Leave blank for "sometime on this trip".
                </div>
                {draft.legs.map((leg, index) => (
                  <div className="leg-row" key={`${leg.country}:${leg.city}`}>
                    <span className="leg-name">{leg.city}</span>
                    <input
                      type="date"
                      aria-label={`${leg.city} from`}
                      min={draft.start_date || undefined}
                      max={draft.end_date || undefined}
                      value={leg.start_date ?? ''}
                      onChange={(e) => setLegDates(index, 'start_date', e.target.value)}
                    />
                    <span className="muted">to</span>
                    <input
                      type="date"
                      aria-label={`${leg.city} to`}
                      min={leg.start_date || draft.start_date || undefined}
                      max={draft.end_date || undefined}
                      value={leg.end_date ?? ''}
                      onChange={(e) => setLegDates(index, 'end_date', e.target.value)}
                    />
                  </div>
                ))}
              </div>
            )}

            <label className="row" style={{ gap: 8 }}>
              <input
                type="checkbox"
                checked={draft.strict_dates}
                onChange={(e) => set('strict_dates', e.target.checked)}
              />
              <span style={{ color: 'var(--text)' }}>Dates are booked and immovable</span>
            </label>

            {!draft.strict_dates && (
              <div className="grid2">
                <div>
                  <label htmlFor="flex-before">Days of slack before</label>
                  <input
                    id="flex-before"
                    type="number"
                    min={0}
                    max={30}
                    value={draft.flex_before}
                    onChange={(e) => set('flex_before', Number(e.target.value))}
                  />
                </div>
                <div>
                  <label htmlFor="flex-after">Days of slack after</label>
                  <input
                    id="flex-after"
                    type="number"
                    min={0}
                    max={30}
                    value={draft.flex_after}
                    onChange={(e) => set('flex_after', Number(e.target.value))}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="modal-foot">
            <button
              className="primary"
              type="submit"
              disabled={saving || !draft.name || !draft.countries.length}
            >
              {saving ? 'Saving…' : trip ? 'Save changes' : 'Create trip'}
            </button>
            <button type="button" onClick={onClose} disabled={saving}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
