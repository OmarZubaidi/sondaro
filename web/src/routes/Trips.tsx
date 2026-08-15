import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Trip } from '../lib/types'
import { prettyDate } from '../lib/format'

export function Trips() {
  const [trips, setTrips] = useState<Trip[] | null>(null)
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const navigate = useNavigate()

  const [form, setForm] = useState({
    name: '',
    countries: '',
    cities: '',
    start_date: '',
    end_date: '',
    flex_before: 3,
    flex_after: 3,
    strict_dates: false,
  })

  useEffect(() => {
    api.trips().then((data) => setTrips(data.trips)).catch((err) => setError(String(err)))
    api.countries().then((data) => setCountries(data.countries)).catch(() => setCountries([]))
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const trip = await api.createTrip({
        ...form,
        countries: form.countries
          .split(',')
          .map((c) => c.trim().toUpperCase())
          .filter(Boolean),
        cities: form.cities.split(',').map((c) => c.trim()).filter(Boolean),
      })
      navigate(`/trips/${trip.id}`)
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <h2>Trips</h2>
      {error && <div className="note">{error}</div>}

      {trips?.length === 0 && (
        <div className="empty">No trips yet. Add one below.</div>
      )}

      {trips?.map((trip) => (
        <div className="card" key={trip.id}>
          <div className="show">
            <div className="body">
              <div className="artist">
                <Link to={`/trips/${trip.id}`}>{trip.name}</Link>
              </div>
              <div className="where">
                {trip.countries.join(' · ')} — {prettyDate(trip.start_date)} to{' '}
                {prettyDate(trip.end_date)}
              </div>
              <div className="chips">
                {trip.strict_dates ? (
                  <span className="chip warn">strict dates</span>
                ) : (
                  <span className="chip">
                    ±{trip.flex_before}/{trip.flex_after} days slack
                  </span>
                )}
                {trip.cities.length > 0 && (
                  <span className="chip">{trip.cities.join(', ')}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}

      <h2>New trip</h2>
      <form className="stack" onSubmit={submit}>
        <div>
          <label htmlFor="trip-name">Name</label>
          <input
            id="trip-name"
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>

        <div>
          <label htmlFor="trip-countries">
            Countries — 2-letter codes, comma separated. Trips can span several.
          </label>
          <input
            id="trip-countries"
            type="text"
            required
            placeholder="FR, ES"
            list="country-codes"
            value={form.countries}
            onChange={(e) => setForm({ ...form, countries: e.target.value })}
          />
          <datalist id="country-codes">
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </datalist>
        </div>

        <div>
          <label htmlFor="trip-cities">
            Cities (optional) — leave empty and the whole country stays in play
          </label>
          <input
            id="trip-cities"
            type="text"
            placeholder="Lyon, Barcelona"
            value={form.cities}
            onChange={(e) => setForm({ ...form, cities: e.target.value })}
          />
        </div>

        <div className="grid2">
          <div>
            <label htmlFor="trip-start">Start</label>
            <input
              id="trip-start"
              type="date"
              required
              value={form.start_date}
              onChange={(e) => setForm({ ...form, start_date: e.target.value })}
            />
          </div>
          <div>
            <label htmlFor="trip-end">End</label>
            <input
              id="trip-end"
              type="date"
              required
              value={form.end_date}
              onChange={(e) => setForm({ ...form, end_date: e.target.value })}
            />
          </div>
        </div>

        <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={form.strict_dates}
            onChange={(e) => setForm({ ...form, strict_dates: e.target.checked })}
          />
          Strict dates — already booked, nothing outside the window
        </label>

        {!form.strict_dates && (
          <div className="grid2">
            <div>
              <label htmlFor="flex-before">Days of slack before</label>
              <input
                id="flex-before"
                type="number"
                min={0}
                max={30}
                value={form.flex_before}
                onChange={(e) => setForm({ ...form, flex_before: Number(e.target.value) })}
              />
            </div>
            <div>
              <label htmlFor="flex-after">Days of slack after</label>
              <input
                id="flex-after"
                type="number"
                min={0}
                max={30}
                value={form.flex_after}
                onChange={(e) => setForm({ ...form, flex_after: Number(e.target.value) })}
              />
            </div>
          </div>
        )}

        <div className="row">
          <button className="primary" type="submit" disabled={saving}>
            {saving ? 'Creating…' : 'Create trip'}
          </button>
        </div>
      </form>
    </>
  )
}
