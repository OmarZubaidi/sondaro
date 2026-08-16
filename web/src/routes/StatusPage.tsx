import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Status } from '../lib/types'
import { percent, relativeTime } from '../lib/format'
import { IndexProgress } from '../components/IndexProgress'

/** The queue's internal kinds, in words. */
const TASK_NAMES: Record<string, string> = {
  artist_lookup: 'Artist lookup',
  library_sync: 'Library sync',
  route_lookup: 'Drive time lookup',
  sweep_geo: 'Nearby sweep',
  sweep_country: 'Country sweep',
  sweep_city: 'City sweep',
}

export function StatusPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [syncing, setSyncing] = useState(false)

  const load = () =>
    api.status().then(setStatus).catch((err) => setError(String(err)))

  useEffect(() => {
    load()
    const timer = setInterval(load, 15_000)
    return () => clearInterval(timer)
  }, [])

  async function sync() {
    setSyncing(true)
    try {
      await api.sync()
      await load()
    } finally {
      setSyncing(false)
    }
  }

  if (error) return <div className="note">{error}</div>
  if (!status) return <div className="empty">Loading…</div>

  return (
    <>
      <IndexProgress status={status} />

      <h2>Index</h2>
      <div className="card">
        <table>
          <tbody>
            <tr>
              <th>Home</th>
              <td>{status.home.label}</td>
            </tr>
            <tr>
              <th>Coverage</th>
              <td>
                {percent(status.coverage)} of {status.horizon_days} days
                {status.reindexing && ' · re-indexing'}
              </td>
            </tr>
            <tr>
              <th>Events cached</th>
              <td>{status.events_cached}</td>
            </tr>
            <tr>
              <th>Worker</th>
              <td>
                {status.worker.running ? 'running' : 'stopped'} ·{' '}
                {status.worker.processed} tasks this session
                {status.worker.last_error && ` · last error: ${status.worker.last_error}`}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>Queue</h2>
      <div className="card">
        {Object.keys(status.queue).length === 0 ? (
          <div className="muted">Nothing queued.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Kind</th>
                <th>Queued</th>
                <th>Due now</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(status.queue).map(([kind, counts]) => (
                <tr key={kind}>
                  <td>{TASK_NAMES[kind] ?? kind}</td>
                  <td>{counts.total}</td>
                  <td>{counts.due}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {status.stalled.length > 0 && (
          <div className="note" style={{ marginTop: 12 }}>
            {status.stalled.length} task(s) exhausted their retries:{' '}
            {status.stalled.map((s) => s.task).join(', ')}
          </div>
        )}
      </div>

      <h2>Provider usage</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Used</th>
              <th>Cap</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {status.quotas.map((quota) => (
              <tr key={quota.provider}>
                <td>{quota.provider}</td>
                <td>{quota.used}</td>
                <td>
                  {quota.cap} /{' '}
                  {quota.window_days === 1 ? 'day' : `${quota.window_days} days`}
                </td>
                <td>
                  <div className="meter" style={{ minWidth: 60 }}>
                    <i
                      style={{
                        width: percent(quota.fraction),
                        background: quota.exhausted ? 'var(--bad)' : 'var(--accent)',
                      }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Library</h2>
      <div className="card">
        <table>
          <tbody>
            <tr>
              <th>Artists</th>
              <td>{status.library.artists}</td>
            </tr>
            <tr>
              <th>Affinity from</th>
              <td>{status.library.affinity_source}</td>
            </tr>
            <tr>
              <th>Last sync</th>
              <td>{relativeTime(status.library.synced_at)}</td>
            </tr>
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}>
          <button type="button" onClick={sync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync library now'}
          </button>
        </div>
      </div>

      {status.sweep_notes.length > 0 && (
        <>
          <h2>Sweep notes</h2>
          {status.sweep_notes.map((note) => (
            <div className="note" key={note}>
              {note}
            </div>
          ))}
        </>
      )}
    </>
  )
}
