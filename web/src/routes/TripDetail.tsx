import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { Show, TripDetail as TripDetailData } from '../lib/types'
import { percent, prettyDate } from '../lib/format'
import { DateGroup } from '../components/DateGroup'
import { ItineraryBuilder } from '../components/ItineraryBuilder'

export function TripDetail() {
  const { id } = useParams<{ id: string }>()
  const tripId = Number(id)
  const navigate = useNavigate()

  const [data, setData] = useState<TripDetailData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [picks, setPicks] = useState<Show[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api
      .trip(tripId)
      .then(setData)
      .catch((err) => setError(String((err as Error).message ?? err)))
  }, [tripId])

  useEffect(load, [load])

  const toggle = useCallback((show: Show) => {
    setPicks((current) =>
      current.some((p) => p.id === show.id)
        ? current.filter((p) => p.id !== show.id)
        : [...current, show],
    )
  }, [])

  async function rescan() {
    setBusy(true)
    try {
      await api.rescanTrip(tripId)
      load()
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!window.confirm('Delete this trip?')) return
    await api.deleteTrip(tripId)
    navigate('/trips')
  }

  if (error) return <div className="note">{error}</div>
  if (!data) return <div className="empty">Loading…</div>

  const { trip } = data
  const pickedIds = new Set(picks.map((p) => p.id))

  return (
    <>
      <h2>{trip.name}</h2>
      <div className="statusbar">
        <span>{trip.countries.join(' · ')}</span>
        <span>
          {prettyDate(trip.start_date)} – {prettyDate(trip.end_date)}
        </span>
        <span>
          {trip.strict_dates
            ? 'strict dates'
            : `±${trip.flex_before}/${trip.flex_after} days`}
        </span>
        <span>{data.total} options</span>
        {data.coverage < 1 && <span>index {percent(data.coverage)}</span>}
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        <button type="button" onClick={rescan} disabled={busy}>
          {busy ? 'Queueing…' : 'Re-scan'}
        </button>
        <a href={`/trips/${tripId}.ics`}>calendar feed</a>
        <button type="button" className="danger" onClick={remove}>
          delete trip
        </button>
      </div>

      {data.coverage < 1 && (
        <div className="progress">
          <strong>Still filling in</strong>
          <div className="muted">
            {percent(data.coverage)} of this trip's window has been fetched.
          </div>
          <div className="bar">
            <i style={{ width: percent(data.coverage) }} />
          </div>
        </div>
      )}

      <h2>Your itinerary</h2>
      <ItineraryBuilder picks={picks} onRemove={toggle} />

      {data.dates.length === 0 ? (
        <div className="empty">
          Nothing found in these countries for these dates yet.
        </div>
      ) : (
        <>
          <h2>All options</h2>
          {data.dates.map((group) => (
            <DateGroup
              key={group.date}
              date={group.date}
              shows={group.shows}
              selectedId={
                group.shows.find((s) => pickedIds.has(s.id))?.id ?? null
              }
              onToggle={toggle}
            />
          ))}
        </>
      )}
    </>
  )
}
