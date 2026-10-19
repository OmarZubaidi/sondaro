import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Trip, TripsFeed } from '../lib/types'
import { dateSpan } from '../lib/format'
import { tripMap } from '../lib/routes'
import { DateGroup } from '../components/DateGroup'
import { CheckList } from '../components/CheckList'
import { LazyRouteMap } from '../components/LazyRouteMap'
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

  // One section per trip, holding whatever turned up for it. A show two trips
  // both want appears under each, and a show you're going to keeps its trip on
  // the page even when the trip filter leaves that trip out.
  const sections = useMemo(() => {
    if (!feed) return []
    return feed.trips.flatMap((trip) => {
      const picked = tripFilter.size === 0 || tripFilter.has(String(trip.id))
      const groups = dates
        .map((group) => ({
          date: group.date,
          shows: group.shows.filter(
            (show) => show.trips?.some((t) => t.id === trip.id) && (picked || show.purchased),
          ),
        }))
        .filter((group) => group.shows.length > 0)
      return picked || groups.length > 0 ? [{ trip, groups }] : []
    })
  }, [feed, dates, tripFilter])

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

  if (error)
    return (
      <div className="wrap">
        <div className="note">{error}</div>
      </div>
    )
  if (!feed)
    return (
      <div className="wrap">
        <div className="empty">Loading…</div>
      </div>
    )

  return (
    <>
      <div className="wrap local-layout">
        <aside className="side tall">
          <h1 className="page-title">Your trips</h1>

          <button
            className="primary block new-trip"
            type="button"
            onClick={() => setEditing('new')}
          >
            New trip
          </button>

          {feed.trips.length > 0 && (
            <>
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

              <div className="tag-field">
                <label htmlFor="trip-min" className="tag">
                  Hide anything below
                </label>
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
          {feed.trips.length === 0 ? (
            <div className="empty">No trips yet. Add one and anything worth seeing while
              you're there turns up here — and in the calendar you already subscribe to.</div>
          ) : (
            sections.map(({ trip, groups }) => (
              <section className="trip-block" key={trip.id} aria-label={trip.name}>
                <div className="trip-header">
                  <div className="trip-hero">
                    <div className="trip-hero-top">
                      <div className="trip-hero-title">
                        <span className="trip-span">
                          {dateSpan(trip.start_date, trip.end_date)}
                        </span>
                        <h2>{trip.name}</h2>
                      </div>
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
                    <ol className="trip-legs">
                      {trip.legs.map((leg) => (
                        <li key={`${leg.country}:${leg.city ?? ''}`}>
                          <span className="leg-place">
                            {leg.city ?? countryNames.get(leg.country) ?? leg.country}
                          </span>
                          {leg.start_date ? (
                            <span className="leg-dates">
                              {dateSpan(leg.start_date, leg.end_date ?? leg.start_date, {
                                year: false,
                              })}
                            </span>
                          ) : (
                            <span
                              className="chip info"
                              title="no city named, so the whole country stays in play"
                            >
                              anywhere, any day
                            </span>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                  <LazyRouteMap
                    {...tripMap(trip, groups.flatMap((group) => group.shows), countryNames)}
                    reachKm={feed.city_reach_km}
                  />
                </div>

                {groups.length === 0 && (perTrip.get(String(trip.id)) ?? 0) > 0 && (
                  <div className="empty">Nothing clears these filters.</div>
                )}
                {groups.map((group) => (
                  <DateGroup
                    key={group.date}
                    date={group.date}
                    shows={group.shows}
                    onChanged={load}
                  />
                ))}
              </section>
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
