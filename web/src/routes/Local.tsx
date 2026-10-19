import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { LocalFeed, SettingSpec } from '../lib/types'
import { relativeTime } from '../lib/format'
import { ShowCard } from '../components/ShowCard'
import { IndexProgress } from '../components/IndexProgress'
import { LocalFilters, type Filters } from '../components/LocalFilters'
import { NextUp } from '../components/NextUp'

const monthId = (label: string) => `month-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`

const DEFAULTS: Filters = {
  weeknight_hours: 3,
  sunday_hours: 3.75,
  weekend_hours: 4.5,
  min_score: 0.05,
}

function fromSpecs(specs: SettingSpec[]): Filters {
  const value = (key: string, fallback: number) => {
    const spec = specs.find((s) => s.key === key)
    return spec ? Number(spec.value) : fallback
  }
  return {
    weeknight_hours: value('base_hours_weeknight', DEFAULTS.weeknight_hours),
    sunday_hours: value('base_hours_sunday', DEFAULTS.sunday_hours),
    weekend_hours: value('base_hours_weekend', DEFAULTS.weekend_hours),
    min_score: value('min_score', DEFAULTS.min_score),
  }
}

export function Local() {
  const [feed, setFeed] = useState<LocalFeed | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)

  // seed the controls from the stored defaults, once
  useEffect(() => {
    api
      .settings()
      .then((payload) => setFilters(fromSpecs(payload.settings)))
      .catch(() => setFilters(DEFAULTS))
  }, [])

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Only the newest response lands, so the refetch after marking a ticket
  // can't overwrite results for filters you've since moved. `quiet` keeps a
  // failed refetch from replacing a page that's still fine with an error.
  const latest = useRef(0)
  const load = useCallback((current: Filters, quiet = false) => {
    const request = ++latest.current
    api
      .home({ ...current })
      .then((data) => request === latest.current && setFeed(data))
      .catch(
        (err) =>
          !quiet && request === latest.current && setError(String(err.message ?? err)),
      )
  }, [])

  useEffect(() => {
    if (!filters) return
    load(filters)

    // remember where the controls were left, without a save button
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => {
      api
        .updateSettings({
          base_hours_weeknight: filters.weeknight_hours,
          base_hours_sunday: filters.sunday_hours,
          base_hours_weekend: filters.weekend_hours,
          min_score: filters.min_score,
        })
        .catch(() => undefined)
    }, 1200)
  }, [filters, load])

  if (error)
    return (
      <div className="wrap">
        <div className="note">Couldn't load shows: {error}</div>
      </div>
    )
  if (!feed || !filters)
    return (
      <div className="wrap">
        <div className="empty">Loading…</div>
      </div>
    )

  const { status } = feed
  const nextUp = feed.months.flatMap((month) => month.shows).find((show) => show.purchased)

  return (
    <>
      <IndexProgress status={status} />

      <div className="wrap local-layout">
        {/* the filters stay put while the list scrolls: they're the reason the
            list looks the way it does, so scrolling away from them is what
            makes a result confusing */}
        <aside className="side tall">
          <h1 className="page-title">Near home</h1>

          <LocalFilters value={filters} onChange={setFilters} />

          {/* one month has nowhere to jump to */}
          {feed.months.length > 1 && (
            <nav className="month-jump" aria-label="Jump to month">
              {feed.months.map((month) => (
                <a key={month.label} href={`#${monthId(month.label)}`}>
                  <span>{month.label}</span> <em>{month.shows.length}</em>
                </a>
              ))}
            </nav>
          )}

          {/* provenance, not navigation — quiet, and out of the way at the end */}
          <div className="side-meta">
            <span>{status.library.artists} artists</span>
            <span>affinity: {status.library.affinity_source}</span>
            <span>synced {relativeTime(status.library.synced_at)}</span>
            <span>{feed.total} upcoming</span>
          </div>
        </aside>

        <div className="feed">
          {nextUp && <NextUp show={nextUp} />}

          {feed.months.length === 0 && (
            <div className="empty">
              Nothing clears these filters.
              {!status.providers.ticketmaster &&
                ' Ticketmaster is not configured, so nothing can be found at all.'}
            </div>
          )}

          {feed.months.map((month) => (
            <section className="month" id={monthId(month.label)} key={month.label}>
              <h2 className="month-label">
                <span>{month.label}</span>
              </h2>
              {month.shows.map((show) => (
                <ShowCard key={show.id} show={show} onChanged={() => load(filters, true)} />
              ))}
            </section>
          ))}
        </div>
      </div>
    </>
  )
}
