import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { IndexProgress } from './IndexProgress'
import type { Status } from '../lib/types'

function status(overrides: Partial<Status> = {}): Status {
  return {
    home: { lat: 38.0, lon: -95.0, label: 'Home' },
    horizon_days: 180,
    coverage: 1,
    reindexing: false,
    queue: {},
    stalled: [],
    quotas: [],
    providers: { ticketmaster: true },
    library: {
      artists: 120,
      synced_at: null,
      affinity_source: 'listenbrainz',
    },
    events_cached: 300,
    routing_host: 'https://api.heigit.org',
    sweep_notes: [],
    worker: { running: true, processed: 12, last_error: null },
    alerts: { threshold: 0.35, muted: false, mute_until: '' },
    degraded: [],
    ...overrides,
  }
}

describe('IndexProgress', () => {
  it('stays out of the way when everything is fine', () => {
    const { container } = render(<IndexProgress status={status()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('says results are incomplete rather than letting them look final', () => {
    render(<IndexProgress status={status({ coverage: 0.34 })} />)

    expect(screen.getByTestId('index-progress')).toBeInTheDocument()
    expect(screen.getByText(/34%/)).toBeInTheDocument()
    expect(screen.getByText(/real, just incomplete/i)).toBeInTheDocument()
  })

  it('names the new home while re-indexing after a move', () => {
    render(
      <IndexProgress
        status={status({
          coverage: 0.1,
          reindexing: true,
          home: { lat: 38.2, lon: -95.2, label: 'Springfield' },
        })}
      />,
    )
    expect(screen.getByText(/Re-indexing for Springfield/)).toBeInTheDocument()
  })

  it('surfaces degradation instead of hiding it', () => {
    render(
      <IndexProgress
        status={status({ degraded: ['jambase quota exhausted for this monthly'] })}
      />,
    )
    expect(screen.getByText(/jambase quota exhausted/)).toBeInTheDocument()
  })

  it('reports how much work is still queued', () => {
    render(
      <IndexProgress
        status={status({ coverage: 0.5, queue: { sweep_geo: { total: 7, due: 2 } } })}
      />,
    )
    expect(screen.getByText(/7 tasks queued/)).toBeInTheDocument()
  })
})
