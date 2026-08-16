import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import type { TripDetail as TripDetailData } from '../lib/types'
import { percent, prettyDate } from '../lib/format'
import { DateGroup } from '../components/DateGroup'
import { TripForm, fieldsFromTrip, toPayload, type TripFields } from '../components/TripForm'
import {
  CalendarIcon,
  EditIcon,
  IconButton,
  RescanIcon,
  TrashIcon,
} from '../components/IconButton'

export function TripDetail() {
  const { id } = useParams<{ id: string }>()
  const tripId = Number(id)
  const navigate = useNavigate()

  const [data, setData] = useState<TripDetailData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([])

  const load = useCallback(() => {
    api
      .trip(tripId)
      .then(setData)
      .catch((err) => setError(String((err as Error).message ?? err)))
  }, [tripId])

  useEffect(load, [load])

  useEffect(() => {
    api.countries().then((d) => setCountries(d.countries)).catch(() => setCountries([]))
  }, [])

  async function save(fields: TripFields) {
    setBusy(true)
    setError(null)
    try {
      await api.updateTrip(tripId, toPayload(fields))
      setEditing(false)
      load()
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setBusy(false)
    }
  }

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

  return (
    <>
      <div className="title-row">
        <h2>{trip.name}</h2>
        <div className="actions">
          <IconButton
            label={editing ? 'Close editor' : 'Edit trip'}
            icon={<EditIcon />}
            onClick={() => setEditing((v) => !v)}
          />
          <IconButton
            label="Re-scan"
            icon={<RescanIcon />}
            onClick={rescan}
            disabled={busy}
          />
          <IconButton
            label="Calendar feed"
            icon={<CalendarIcon />}
            href={`/trips/${tripId}.ics`}
          />
          <IconButton
            label="Delete trip"
            icon={<TrashIcon />}
            onClick={remove}
            tone="danger"
          />
        </div>
      </div>
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

      {data.notes?.map((note) => (
        <div className="note" key={note}>
          {note}
        </div>
      ))}

      {editing && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ marginTop: 0 }}>Edit trip</h2>
          <TripForm
            initial={fieldsFromTrip(trip)}
            countries={countries}
            submitLabel="Save changes"
            busy={busy}
            onSubmit={save}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}

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
            />
          ))}
        </>
      )}
    </>
  )
}
