import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { FavoritesFeed, Show } from '../lib/types'
import { dateSpan } from '../lib/format'
import { ArtistPhoto } from '../components/ArtistPhoto'
import { CheckList } from '../components/CheckList'
import { ShowCard } from '../components/ShowCard'
import { TripRun } from '../components/TripRun'

type View = 'artists' | 'trips'

const VIEWS: { value: View; label: string }[] = [
  { value: 'artists', label: 'By artist' },
  { value: 'trips', label: 'Could-be trips' },
]

/** One date, flattened out of the artist/country nesting the API sends so it
 *  can be filtered and regrouped on either axis. */
interface Entry {
  show: Show
  artistKey: string
  artistName: string
  code: string
  country: string
}

/** One artist's consecutive dates inside a trip. */
interface Run {
  key: string
  artist: string
  shows: Show[]
}

interface Trip {
  key: string
  label: string
  summary: string
  runs: Run[]
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`
}

/** Split a trip's dates into consecutive same-artist runs.
 *
 *  Consecutive, not pooled: an act playing either side of another one is two
 *  separate runs, because the gap between them is a gap you'd have to fill.
 */
function runs(entries: Entry[]): Run[] {
  const out: Run[] = []
  for (const entry of entries) {
    const last = out[out.length - 1]
    if (last && last.artist === entry.artistName) {
      last.shows.push(entry.show)
      continue
    }
    out.push({ key: entry.show.id, artist: entry.artistName, shows: [entry.show] })
  }
  return out
}

export function Favorites() {
  const [feed, setFeed] = useState<FavoritesFeed | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('artists')
  const [artistFilter, setArtistFilter] = useState<Set<string>>(new Set())
  const [countryFilter, setCountryFilter] = useState<Set<string>>(new Set())
  const [shape, setShape] = useState<{ days: number; km: number } | null>(null)

  const load = useCallback((next?: { days: number; km: number }) => {
    api
      .favorites(next)
      .then((payload) => {
        setFeed(payload)
        // adopt the stored shape on the first load, so the controls open where
        // they were left rather than on a hardcoded pair of numbers
        setShape(
          (current) => current ?? { days: payload.cluster_days, km: payload.cluster_km },
        )
      })
      .catch((err) => setError(String((err as Error).message ?? err)))
  }, [])

  useEffect(() => load(), [load])

  // Re-clustering is a re-read of cached events, never a fetch, so the knobs
  // can drive the request directly. The debounced write only remembers them.
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    },
    [],
  )

  function reshape(next: { days: number; km: number }) {
    setShape(next)
    load(next)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      api
        .updateSettings({ cluster_days: next.days, cluster_km: next.km })
        .catch(() => undefined)
    }, 1200)
  }

  const entries = useMemo<Entry[]>(
    () =>
      (feed?.artists ?? []).flatMap((artist) =>
        artist.countries.flatMap((country) =>
          country.shows.map((show) => ({
            show,
            artistKey: artist.key,
            artistName: artist.name,
            code: country.code,
            country: country.name,
          })),
        ),
      ),
    [feed],
  )

  // Filtering and regrouping are client-side: every control re-reads what's
  // already on the page, so nothing here costs an API call.
  const filtering = artistFilter.size + countryFilter.size > 0
  const shown = useMemo(
    () =>
      entries.filter(
        (entry) =>
          (artistFilter.size === 0 || artistFilter.has(entry.artistKey)) &&
          // the country filter belongs to the artist view; trips are found by
          // where the dates actually fall, not by where you went looking
          (view === 'trips' || countryFilter.size === 0 || countryFilter.has(entry.code)),
      ),
    [entries, artistFilter, countryFilter, view],
  )

  // Counts come off the unfiltered feed, so a row reading zero stays a fact
  // about your library rather than about the boxes you happen to have ticked.
  const perCountry = useMemo(() => {
    const dates = new Map<string, number>()
    for (const entry of entries) {
      dates.set(entry.code, (dates.get(entry.code) ?? 0) + 1)
    }
    return dates
  }, [entries])

  /** A cluster of a single act is not a trip — you wouldn't fly out to see the
   *  same band four times — so it is not offered as one. The artist view still
   *  lists those dates in full. */
  const trips = useMemo<Trip[]>(() => {
    if (!feed || view !== 'trips') return []

    const buckets = new Map<number, Entry[]>()
    for (const entry of shown) {
      const id = entry.show.cluster
      if (id === null || id === undefined) continue
      if (!buckets.has(id)) buckets.set(id, [])
      buckets.get(id)!.push(entry)
    }

    const found: Trip[] = []
    for (const cluster of feed.clusters) {
      const dates = (buckets.get(cluster.id) ?? []).sort((a, b) =>
        a.show.date.localeCompare(b.show.date),
      )
      const artists = new Set(dates.map((entry) => entry.artistKey))
      if (artists.size < 2) continue

      found.push({
        key: `trip-${cluster.id}`,
        label: dateSpan(cluster.start_date, cluster.end_date),
        summary: `${plural(artists.size, 'favorite')} · ${plural(dates.length, 'date')}`,
        runs: runs(dates),
      })
    }
    return found
  }, [feed, shown, view])

  const byArtist = useMemo(() => {
    if (!feed || view !== 'artists') return []

    const grouped = new Map<string, Entry[]>()
    for (const entry of shown) {
      if (!grouped.has(entry.artistKey)) grouped.set(entry.artistKey, [])
      grouped.get(entry.artistKey)!.push(entry)
    }

    // Artist order is the feed's, which is ranked. An artist with nothing
    // matching keeps a row only when nothing is filtered: that absence answers
    // "is anyone I like touring", where under a filter it's just noise.
    return feed.artists
      .filter((artist) => grouped.has(artist.key) || !filtering)
      .map((artist) => {
        const dates = (grouped.get(artist.key) ?? []).sort((a, b) =>
          a.show.date.localeCompare(b.show.date),
        )
        return {
          artist,
          dates,
          quiet: dates.length
            ? null
            : artist.searching
              ? 'Still looking — nothing worldwide for them yet.'
              : `Nothing announced anywhere before ${feed.searched_to}.`,
        }
      })
  }, [feed, shown, view, filtering])

  if (error)
    return (
      <div className="wrap">
        <div className="note">Couldn't load favorites: {error}</div>
      </div>
    )
  if (!feed || !shape)
    return (
      <div className="wrap">
        <div className="empty">Loading…</div>
      </div>
    )

  const empty = view === 'trips' ? trips.length === 0 : byArtist.length === 0

  return (
    <div className="wrap local-layout">
      <aside className="side tall">
        <h1 className="page-title">Artists</h1>

        <div className="tabs" role="tablist" aria-label="View">
          {VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={view === option.value}
              onClick={() => setView(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {/* What counts as one trip. One grid rather than two rows, so the
            labels, fields and units line up in columns instead of drifting.
            Only meaningful here, so it only appears here. */}
        {view === 'trips' && (
          <div className="trip-shape">
            <label htmlFor="fav-days">Within</label>
            <input
              id="fav-days"
              type="number"
              min={1}
              max={60}
              step={1}
              value={shape.days}
              onChange={(e) =>
                reshape({
                  ...shape,
                  days: Math.min(60, Math.max(1, Number(e.target.value) || 1)),
                })
              }
            />
            <span>days</span>

            <label htmlFor="fav-km">and</label>
            <input
              id="fav-km"
              type="number"
              min={25}
              max={3000}
              step={50}
              value={shape.km}
              onChange={(e) =>
                reshape({
                  ...shape,
                  km: Math.min(3000, Math.max(25, Number(e.target.value) || 25)),
                })
              }
            />
            <span>km</span>
          </div>
        )}

        <CheckList
          legend="Artists"
          selected={artistFilter}
          onChange={setArtistFilter}
          // an artist touring nowhere is not a filter, it's a blank row
          options={feed.artists
            .filter((artist) => artist.total > 0)
            .map((artist) => ({
              value: artist.key,
              label: artist.name,
              count: artist.total,
            }))}
        />

        {view === 'artists' && (
          <CheckList
            legend="Countries"
            selected={countryFilter}
            onChange={setCountryFilter}
            options={feed.countries.map((country) => ({
              value: country.code,
              label: country.name,
              count: perCountry.get(country.code) ?? 0,
            }))}
          />
        )}
      </aside>

      <div className={`feed${view === 'artists' ? ' tight' : ''}`}>
        {feed.artists.length === 0 ? (
          <div className="empty">
            Nothing in the library yet. Sondaro follows what's in Lidarr, so add an
            artist there and they'll turn up here.
          </div>
        ) : empty ? (
          <div className="empty">
            {view === 'trips'
              ? 'No trips. A trip needs two favorites close enough together to catch on one journey — widen the window or the radius.'
              : 'Nothing clears these filters.'}
          </div>
        ) : view === 'trips' ? (
          trips.map((trip) => (
            <section className="trip" key={trip.key}>
              <div className="trip-head">
                <h2>{trip.label}</h2>
                <span className="trip-summary">{trip.summary}</span>
              </div>
              <div className="trip-body">
                {trip.runs.map((run) => (
                  <TripRun
                    key={run.key}
                    artist={run.artist}
                    shows={run.shows}
                    onChanged={() => load(shape)}
                  />
                ))}
              </div>
            </section>
          ))
        ) : (
          byArtist.map(({ artist, dates, quiet }) => {
            const head = (
              <>
                <ArtistPhoto
                  src={artist.image?.poster ?? artist.image?.fanart}
                  className="favorite-thumb"
                />
                <div className="favorite-name">
                  <h2>{artist.name}</h2>
                  {artist.slipped && (
                    <span
                      className="chip slipped"
                      title="Followed for a month after slipping, so a trip you're planning around doesn't vanish under you. Their dates are already cached either way."
                    >
                      slipped out of your top {feed.follows}
                    </span>
                  )}
                </div>
                {dates.length > 0 && (
                  <span className="favorite-meta">
                    <span>{plural(dates.length, 'date')}</span>
                    <span className="chevron" aria-hidden="true">
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="3"
                      >
                        <path d="M6 9l6 6 6-6" />
                      </svg>
                    </span>
                  </span>
                )}
              </>
            )

            // Nothing to collapse, so no control that implies there is.
            if (quiet) {
              return (
                <section className="favorite" key={artist.key}>
                  <div className="favorite-head">{head}</div>
                  <p className="favorite-quiet">{quiet}</p>
                </section>
              )
            }

            return (
              <details
                className="favorite"
                key={artist.key}
                // Open under a filter: you narrowed the page to find
                // something, and hiding the result behind a click would be
                // the opposite of an answer.
                open={filtering}
              >
                <summary className="favorite-head">{head}</summary>
                {dates.map((entry) => (
                  <ShowCard
                    key={entry.show.id}
                    show={entry.show}
                    compact
                    showScore={false}
                    showCountry={false}
                    countryName={entry.country}
                    onChanged={() => load(shape)}
                  />
                ))}
              </details>
            )
          })
        )}
      </div>
    </div>
  )
}
