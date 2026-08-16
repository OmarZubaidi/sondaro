import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { Trip } from '../lib/types'
import { prettyDate } from '../lib/format'
import { TripForm, toPayload, type TripFields } from '../components/TripForm'

const BLANK: TripFields = {
  name: '',
  countries: '',
  cities: '',
  start_date: '',
  end_date: '',
  flex_before: 3,
  flex_after: 3,
  strict_dates: false,
}

export function Trips() {
  const [trips, setTrips] = useState<Trip[] | null>(null)
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    api.trips().then((data) => setTrips(data.trips)).catch((err) => setError(String(err)))
    api.countries().then((data) => setCountries(data.countries)).catch(() => setCountries([]))
  }, [])

  async function create(fields: TripFields) {
    setSaving(true)
    setError(null)
    try {
      const trip = await api.createTrip(toPayload(fields))
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

      {trips?.length === 0 && <div className="empty">No trips yet. Add one below.</div>}

      {trips?.map((trip) => (
        <div className="card" key={trip.id}>
          <div className="show">
            <div className="body">
              <div className="artist">
                <Link to={`/trips/${trip.id}`}>{trip.name}</Link>
              </div>
              <div className="where">
                {trip.countries.join(' · ')} · {prettyDate(trip.start_date)} to{' '}
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
                {trip.cities.length > 0 ? (
                  <span className="chip">{trip.cities.join(', ')}</span>
                ) : (
                  <span className="chip">no cities named</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}

      <h2>New trip</h2>
      <TripForm
        initial={BLANK}
        countries={countries}
        submitLabel="Create trip"
        busy={saving}
        onSubmit={create}
      />
    </>
  )
}
