import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Trip, TripsFeed } from '../lib/types'
import { DateGroup } from '../components/DateGroup'
import { CheckList } from '../components/CheckList'
import { TripModal } from '../components/TripModal'
import { EditIcon, IconButton, TrashIcon } from '../components/IconButton'

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

  // a bare "FR" on a leg is a code you have to decode; the picker already
  // loaded the names for the modal
  const countryNames = useMemo(
    () => new Map(countries.map((c) => [c.code, c.name])),
    [countries],
  )

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
          </div>

          <button className="primary block" type="button" onClick={() => setEditing('new')}>
            New trip
          </button>

          {/* The itinerary, then which trips, then how to narrow them.
              Collapsible because it's reference material: you read it when
              you're wondering where you'll be, not on every visit. */}
          {feed.trips.length > 0 && (
            <>
              <details className="card filters trip-list" open>
                <summary>
                  Itinerary <em>{feed.trips.length}</em>
                </summary>
                {feed.trips.map((trip) => (
                  <div className="trip-row" key={trip.id}>
                    <div className="trip-row-head">
                      <strong title={trip.name}>{trip.name}</strong>
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
                    <div className="muted trip-span">
                      {trip.start_date} – {trip.end_date}
                    </div>
                    <ul className="trip-legs">
                      {trip.legs.map((leg) => (
                        <li key={`${leg.country}:${leg.city ?? ''}`}>
                          <span className={leg.city ? undefined : 'loose'}>
                            {leg.city ?? countryNames.get(leg.country) ?? leg.country}
                          </span>
                          {leg.start_date ? (
                            <span className="muted">
                              {leg.start_date}
                              {leg.end_date && ` – ${leg.end_date}`}
                            </span>
                          ) : (
                            <span
                              className="muted"
                              title="no city named, so the whole country stays in play"
                            >
                              anywhere, any day
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </details>

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

                {/* every country the trips touch, including the ones showing
                    nothing — a row reading 0 is what the explanatory banners
                    used to say, at a fraction of the page */}
                <CheckList
                  legend="Countries"
                  selected={countryFilter}
                  onChange={setCountryFilter}
                  options={feed.countries.map((c) => {
                    const found = perCountry.get(c.code) ?? 0
                    return {
                      value: c.code,
                      label: c.name,
                      count: found === 0 && c.searching ? '…' : found,
                      hint:
                        c.note ??
                        (found === 0 && c.searching
                          ? 'Still being searched, so this may not be the final answer.'
                          : undefined),
                    }
                  })}
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

        {/* nothing but results: the itinerary that used to sit on top of them
            is in the sidebar, where it doesn't push the answer below the fold */}
        <div className="feed">
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
