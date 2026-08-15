import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { HomeFeed } from '../lib/types'
import { relativeTime } from '../lib/format'
import { ShowCard } from '../components/ShowCard'
import { IndexProgress } from '../components/IndexProgress'

export function Home() {
  const [feed, setFeed] = useState<HomeFeed | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .home()
      .then((data) => !cancelled && setFeed(data))
      .catch((err) => !cancelled && setError(String(err.message ?? err)))
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <div className="note">Couldn't load shows: {error}</div>
  if (!feed) return <div className="empty">Loading…</div>

  const { status } = feed

  return (
    <>
      <IndexProgress status={status} />

      <div className="statusbar">
        <span>{status.library.artists} artists</span>
        <span>affinity: {status.library.affinity_source}</span>
        <span>synced {relativeTime(status.library.synced_at)}</span>
        <span>{feed.total} upcoming</span>
      </div>

      <div className="row" style={{ marginBottom: 16 }}>
        <a href="/calendar.ics">calendar feed</a>
      </div>

      {feed.months.length === 0 && (
        <div className="empty">
          Nothing found yet.
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
    </>
  )
}
