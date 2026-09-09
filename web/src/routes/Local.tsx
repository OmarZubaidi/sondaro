import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { LocalFeed, SettingSpec } from '../lib/types'
import { relativeTime } from '../lib/format'
import { ShowCard } from '../components/ShowCard'
import { IndexProgress } from '../components/IndexProgress'
import { LocalFilters, type Filters } from '../components/LocalFilters'

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

  useEffect(() => {
    if (!filters) return
    let canceled = false

    api
      .home({ ...filters })
      .then((data) => !canceled && setFeed(data))
      .catch((err) => !canceled && setError(String(err.message ?? err)))

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

    return () => {
      canceled = true
    }
  }, [filters])

  if (error) return <div className="note">Couldn't load shows: {error}</div>
  if (!feed || !filters) return <div className="empty">Loading…</div>

  const { status } = feed

  return (
    <>
      <IndexProgress status={status} />

      <div className="local-layout">
        {/* the filters stay put while the list scrolls: they're the reason the
            list looks the way it does, so scrolling away from them is what
            makes a result confusing */}
        <aside className="side">
          <div className="title-row">
            <h2>Local</h2>
          </div>

          <LocalFilters value={filters} onChange={setFilters} />

          {/* provenance, not navigation — quiet, and out of the way at the end */}
          <div className="side-meta">
            <span>{status.library.artists} artists</span>
            <span>affinity: {status.library.affinity_source}</span>
            <span>synced {relativeTime(status.library.synced_at)}</span>
            <span>{feed.total} upcoming</span>
          </div>
        </aside>

        <div className="feed">
          {feed.months.length === 0 && (
            <div className="empty">
              Nothing clears these filters.
              {!status.providers.ticketmaster &&
                ' Ticketmaster is not configured, so nothing can be found at all.'}
            </div>
          )}

          {feed.months.map((month) => (
            <section key={month.label}>
              <h2>{month.label}</h2>
              {month.shows.map((show) => (
                <ShowCard key={show.id} show={show} />
              ))}
            </section>
          ))}
        </div>
      </div>
    </>
  )
}
