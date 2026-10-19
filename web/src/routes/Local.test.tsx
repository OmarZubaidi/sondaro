import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Local } from './Local'
import { api } from '../lib/api'
import type { LocalFeed, Show, Status } from '../lib/types'

function show(id: string, artist: string, date: string, overrides: Partial<Show> = {}): Show {
  return {
    id,
    artist,
    listens: 10,
    score: 0.6,
    affinity: 0.6,
    date_fit: 1,
    reach_fit: 1,
    flags: [],
    reasons: [],
    drive_hours: 1,
    km: 80,
    date,
    time: '20:00',
    venue: `${artist} Hall`,
    city: 'Utrecht',
    region: null,
    country: 'NL',
    lat: 52,
    lon: 5,
    url: null,
    provider: 'ticketmaster',
    purchased: false,
    ...overrides,
  }
}

const STATUS: Status = {
  home: { lat: 52, lon: 5, label: 'Utrecht' },
  horizon_days: 365,
  coverage: 1,
  reindexing: false,
  queue: {},
  stalled: [],
  quotas: [],
  providers: { ticketmaster: true },
  library: { artists: 120, synced_at: null, affinity_source: 'listenbrainz' },
  events_cached: 300,
  routing_host: null,
  sweep_notes: [],
  worker: { running: true, processed: 0, last_error: null },
  alerts: { threshold: 0.35, muted: false, mute_until: '' },
  degraded: [],
}

const MONTHS: LocalFeed['months'] = [
  {
    label: 'November 2026',
    shows: [show('a', 'Fontaines D.C.', '2026-11-06'), show('b', 'Big Thief', '2026-11-12')],
  },
  { label: 'December 2026', shows: [show('c', 'Khruangbin', '2026-12-04')] },
]

function feed(months: LocalFeed['months'] = MONTHS): LocalFeed {
  return {
    total: months.reduce((sum, month) => sum + month.shows.length, 0),
    months,
    status: STATUS,
  }
}

async function renderLocal(payload: LocalFeed = feed()) {
  vi.spyOn(api, 'settings').mockResolvedValue({
    settings: [],
    credentials: {},
    quotas: [],
    tailnet_url: '',
  })
  vi.spyOn(api, 'home').mockResolvedValue(payload)
  // the controls remember themselves on a debounce; keep it off the network
  vi.spyOn(api, 'updateSettings').mockResolvedValue({ updated: {} })
  render(<Local />)
  await screen.findByRole('heading', { name: 'Near home' })
}

describe('Local', () => {
  describe('the month jump list', () => {
    it('links to every month, with how many shows it holds', async () => {
      await renderLocal()

      const nav = screen.getByRole('navigation', { name: 'Jump to month' })
      const links = within(nav).getAllByRole('link')
      expect(links.map((link) => link.textContent)).toEqual(['November 2026 2', 'December 2026 1'])
      expect(links.map((link) => link.getAttribute('href'))).toEqual([
        '#month-november-2026',
        '#month-december-2026',
      ])
    })

    it('points each link at its month', async () => {
      await renderLocal()

      const target = document.getElementById('month-december-2026')!
      expect(within(target).getByRole('heading', { name: 'December 2026' })).toBeInTheDocument()
      expect(within(target).getByText('Khruangbin')).toBeInTheDocument()
    })

    it('is left out when there is only one month to jump to', async () => {
      await renderLocal(feed(MONTHS.slice(0, 1)))

      expect(screen.queryByRole('navigation', { name: 'Jump to month' })).toBeNull()
    })
  })
})
