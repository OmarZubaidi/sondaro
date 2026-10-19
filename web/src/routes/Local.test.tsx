import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  describe('the next-up block', () => {
    /** The same months, with tickets bought for the given show ids. */
    const bought = (...ids: string[]): LocalFeed['months'] =>
      MONTHS.map((month) => ({
        ...month,
        shows: month.shows.map((s) => ({ ...s, purchased: ids.includes(s.id) })),
      }))

    it('puts the next show you’re going to above the list', async () => {
      await renderLocal(feed(bought('b', 'c')))

      const next = screen.getByRole('region', { name: 'Next up' })
      expect(within(next).getByText('Big Thief')).toBeInTheDocument()
      expect(within(next).getByText('Thursday · 20:00')).toBeInTheDocument()
      expect(within(next).getByText('12')).toBeInTheDocument()
      expect(within(next).getByText('Nov 2026')).toBeInTheDocument()
      expect(within(next).getByText('Big Thief Hall, Utrecht, NL · 1h drive · 80 km')).toBeInTheDocument()
    })

    it('is left out when no ticket is bought', async () => {
      await renderLocal()

      expect(screen.queryByRole('region', { name: 'Next up' })).toBeNull()
    })

    it('appears once you mark a ticket bought, without a reload', async () => {
      await renderLocal()
      vi.spyOn(api, 'setPurchased').mockResolvedValue({ id: 'c', purchased: true })
      vi.mocked(api.home).mockResolvedValue(feed(bought('c')))

      const row = screen.getByText('Khruangbin').closest<HTMLElement>('.show-row')!
      await userEvent.click(within(row).getByRole('button', { name: 'mark as bought' }))

      const next = await screen.findByRole('region', { name: 'Next up' })
      expect(within(next).getByText('Khruangbin')).toBeInTheDocument()
    })
  })
})
