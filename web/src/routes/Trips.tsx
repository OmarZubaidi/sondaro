import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Trip, TripsFeed } from '../lib/types'
import { DateGroup } from '../components/DateGroup'
import { CheckList } from '../components/CheckList'
import { TripModal } from '../components/TripModal'
import { EditIcon, IconButton, TrashIcon } from '../components/IconButton'
import { CalendarLink } from '../components/CalendarLink'

export function Trips() {
  const [feed, setFeed] = useState<TripsFeed | null>(null)
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Trip | 'new' | null>(null)

  const [tripFilter, setTripFilter] = useState<Set<string>>(new Set())
  const [countryFilter, setCountryFilter] = useState<Set<string>>(new Set())
  const [minScore, setMinScore] = useState(0.05)

  const load = useCallback(() => {
    api
      .trips()
      .then(setFeed)
      .catch((err) => setError(String((err as Error).message ?? err)))
  }, [])

  useEffect(load, [load])
  useEffect(() => {
    api.countries().then((d) => setCountries(d.countries)).catch(() => setCountries([]))
  }, [])

  // Filtering is client-side on purpose: every one of these re-reads data
  // already on the page, so ticking a box is instant and costs nothing.
  const dates = useMemo(() => {
    if (!feed) return []
    return feed.dates
      .map((group) => ({
        date: group.date,
        shows: group.shows.filter((show) => {
          if (show.purchased) return true // you're going; no filter applies
          if (show.score < minScore) return false
          if (countryFilter.size && !countryFilter.has(show.country ?? '')) return false
          if (tripFilter.size && !show.trips?.some((t) => tripFilter.has(String(t.id))))
            return false
          return true
        }),
      }))
      .filter((group) => group.shows.length > 0)
  }, [feed, minScore, countryFilter, tripFilter])

  const shown = dates.reduce((sum, group) => sum + group.shows.length, 0)

  const perTrip = useMemo(() => {
    const counts = new Map<string, number>()
    for (const group of feed?.dates ?? [])
      for (const show of group.shows)
        for (const trip of show.trips ?? [])
          counts.set(String(trip.id), (counts.get(String(trip.id)) ?? 0) + 1)
    return counts
  }, [feed])

  const perCountry = useMemo(() => {
    const counts = new Map<string, number>()
    for (const group of feed?.dates ?? [])
      for (const show of group.shows)
        if (show.country) counts.set(show.country, (counts.get(show.country) ?? 0) + 1)
    return counts
  }, [feed])

  async function remove(trip: Trip) {
    if (!window.confirm(`Delete "${trip.name}"?`)) return
    await api.deleteTrip(trip.id)
    load()
  }

  if (error) return <div className="note">{error}</div>
  if (!feed) return <div className="empty">Loading…</div>

  return (
    <>
      <div className="local-layout">
        <aside className="side">
          <div className="title-row">
            <h2>Trips</h2>
            <div className="actions">
              <CalendarLink />
            </div>
          </div>

          <button className="primary block" type="button" onClick={() => setEditing('new')}>
            New trip
          </button>

          {/* Which trips, then how to narrow them. Picking a trip is closer to
              navigation than to filtering — it's the first thing you reach for
              and it belongs next to the button that makes one. */}
          {feed.trips.length > 0 && (
            <>
              <div className="card filters">
                <CheckList
                  legend="Trips"
                  selected={tripFilter}
                  onChange={setTripFilter}
                  options={feed.trips.map((trip) => ({
                    value: String(trip.id),
                    label: trip.name,
                    count: perTrip.get(String(trip.id)) ?? 0,
                  }))}
                />
              </div>

              <div className="card filters">
                <div className="inline-field">
                  <label htmlFor="trip-min">Hide anything below</label>
                  <input
                    id="trip-min"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={minScore}
                    onChange={(e) =>
                      setMinScore(Math.min(1, Math.max(0, Number(e.target.value) || 0)))
                    }
                  />
                </div>

                <CheckList
                  legend="Countries"
                  selected={countryFilter}
                  onChange={setCountryFilter}
                  options={feed.countries.map((c) => ({
                    value: c.code,
                    label: c.name,
                    count: perCountry.get(c.code) ?? 0,
                  }))}
                />
              </div>
            </>
          )}

          <div className="side-meta">
            <span>
              {feed.trips.length} trip{feed.trips.length === 1 ? '' : 's'}
            </span>
            <span>
              {shown} of {feed.total} shown
            </span>
          </div>
        </aside>

        <div className="feed">
          {feed.notes.map((note) => (
            <div className="note" key={note}>
              {note}
            </div>
          ))}

          {feed.trips.length > 0 && (
            <div className="trip-strip">
              {feed.trips.map((trip) => (
                <div className="card trip-card" key={trip.id}>
                  <div>
                    <strong>{trip.name}</strong>
                    <div className="muted">
                      {trip.start_date} – {trip.end_date}
                    </div>
                    <div className="chips">
                      {trip.legs.map((leg) => (
                        <span
                          className={`chip${leg.city ? '' : ' info'}`}
                          key={`${leg.country}:${leg.city ?? ''}`}
                          title={leg.city ? undefined : 'no city named, so the whole country is in play'}
                        >
                          {leg.city ?? leg.country}
                          {leg.start_date && (
                            <> · {leg.start_date}
                              {leg.end_date && `–${leg.end_date}`}
                            </>
                          )}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="actions">
                    <IconButton
                      label={`Edit ${trip.name}`}
                      icon={<EditIcon />}
                      onClick={() => setEditing(trip)}
                    />
                    <IconButton
                      label={`Delete ${trip.name}`}
                      icon={<TrashIcon />}
                      tone="danger"
                      onClick={() => remove(trip)}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {feed.trips.length === 0 ? (
            <div className="empty">No trips yet. Add one and anything worth seeing while
              you're there turns up here — and in the calendar you already subscribe to.</div>
          ) : dates.length === 0 ? (
            <div className="empty">Nothing clears these filters.</div>
          ) : (
            dates.map((group) => (
              <DateGroup key={group.date} date={group.date} shows={group.shows} onChanged={load} />
            ))
          )}
        </div>
      </div>

      {editing && (
        <TripModal
          trip={editing === 'new' ? undefined : editing}
          countries={countries}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            load()
          }}
        />
      )}
    </>
  )
}
