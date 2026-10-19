import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Favorites } from './Favorites'
import { api } from '../lib/api'
import type { Cluster, FavoriteArtist, FavoritesFeed, Show } from '../lib/types'

const COUNTRY_NAMES: Record<string, string> = {
  US: 'United States of America',
  DE: 'Germany',
  JP: 'Japan',
}

interface Date_ {
  date: string
  city: string
  code: string
  cluster: number
  region?: string
  venue?: string
}

interface Spec {
  name: string
  dates: Date_[]
  slipped?: boolean
  searching?: boolean
}

function show(artist: string, date: Date_): Show {
  return {
    id: `${artist}-${date.date}-${date.city}`,
    artist,
    listens: 5000,
    score: 1,
    affinity: 1,
    date_fit: 1,
    reach_fit: 1,
    flags: [],
    reasons: [],
    // no origin to measure from, so the api sends neither
    drive_hours: null,
    km: null,
    date: date.date,
    time: '19:30',
    venue: date.venue ?? `${date.city} Hall`,
    city: date.city,
    region: date.region ?? null,
    country: date.code,
    lat: 0,
    lon: 0,
    url: `https://example.test/${artist}-${date.date}`,
    provider: 'ticketmaster',
    purchased: false,
    cluster: date.cluster,
  }
}

function makeFeed(
  specs: Spec[],
  clusters: Cluster[] = [],
  overrides: Partial<FavoritesFeed> = {},
): FavoritesFeed {
  const artists: FavoriteArtist[] = specs.map((spec) => {
    const byCode = new Map<string, Show[]>()
    for (const date of spec.dates) {
      if (!byCode.has(date.code)) byCode.set(date.code, [])
      byCode.get(date.code)!.push(show(spec.name, date))
    }
    return {
      key: `name:${spec.name.toLowerCase()}`,
      name: spec.name,
      listens: 5000,
      affinity: 1,
      searching: spec.searching ?? false,
      slipped: spec.slipped ?? false,
      total: spec.dates.length,
      countries: [...byCode].map(([code, shows]) => ({
        code,
        name: COUNTRY_NAMES[code] ?? code,
        shows,
      })),
    }
  })

  const codes = [...new Set(specs.flatMap((s) => s.dates.map((d) => d.code)))].sort()
  return {
    artists,
    clusters,
    total: specs.reduce((sum, spec) => sum + spec.dates.length, 0),
    follows: 10,
    cluster_days: 12,
    cluster_km: 650,
    searched_to: '2027-03-08',
    countries: codes.map((code) => ({ code, name: COUNTRY_NAMES[code] ?? code })),
    ...overrides,
  }
}

const tx = (date: string, city: string, cluster = 0, venue?: string): Date_ => ({
  date,
  city,
  code: 'US',
  region: 'TX',
  cluster,
  venue,
})

/** The reported case: four acts across one Texas swing, in runs. */
const TEXAS: Spec[] = [
  {
    name: 'Empire of the Sun',
    dates: [
      tx('2026-09-20', 'Dallas', 0, 'Dos Equis Pavilion'),
      tx('2026-09-21', 'Austin', 0, 'Moody Center ATX'),
      tx('2026-09-24', 'The Woodlands', 0),
    ],
  },
  {
    name: 'Saint Levant',
    dates: [
      tx('2026-10-06', 'Dallas', 0, 'South Side Ballroom'),
      tx('2026-10-07', 'Austin', 0),
    ],
  },
  { name: 'Gorillaz', dates: [tx('2026-10-15', 'Austin', 0), tx('2026-10-16', 'Fort Worth', 0)] },
  { name: 'System of a Down', dates: [tx('2026-10-24', 'Fort Worth', 0)] },
]

const TEXAS_CLUSTERS: Cluster[] = [
  { id: 0, start_date: '2026-09-20', end_date: '2026-10-24', places: ['TX'] },
]

/** One act either side of another: two runs, not one. */
const INTERLEAVED: Spec[] = [
  {
    name: 'Empire of the Sun',
    dates: [tx('2026-09-20', 'Dallas'), tx('2026-10-20', 'Houston')],
  },
  { name: 'Gorillaz', dates: [tx('2026-10-01', 'Austin')] },
]

/** A cluster that is one act's own tour leg, which is not a trip. */
const SOLO_ACT: Spec[] = [
  {
    name: 'Empire of the Sun',
    dates: [tx('2026-09-20', 'Dallas'), tx('2026-09-21', 'Austin')],
  },
]

const SOLO_CLUSTERS: Cluster[] = [
  { id: 0, start_date: '2026-09-20', end_date: '2026-09-21', places: ['TX'] },
]

async function renderFeed(payload: FavoritesFeed = makeFeed(TEXAS, TEXAS_CLUSTERS)) {
  vi.spyOn(api, 'favorites').mockResolvedValue(payload)
  // the trip-shape controls remember themselves on a debounce; stub the write
  // so a pending timer can't reach the network
  vi.spyOn(api, 'updateSettings').mockResolvedValue({ updated: {} })
  render(<Favorites />)
  await screen.findByRole('heading', { name: 'Artists' })
}

function bands(): (string | null)[] {
  return screen
    .getAllByRole('heading')
    .map((node) => node.textContent)
    .filter((text) => text !== 'Artists')
}

const trips = () => userEvent.click(screen.getByRole('tab', { name: 'Could-be trips' }))
const artists = () => userEvent.click(screen.getByRole('tab', { name: 'By artist' }))
const tick = (name: RegExp) => userEvent.click(screen.getByRole('checkbox', { name }))

/** Run headings inside the feed, in order. */
function runHeads(): string[] {
  return Array.from(document.querySelectorAll('.run-head strong')).map(
    (node) => node.textContent ?? '',
  )
}

function rowsUnder(artist: string): string[] {
  const head = Array.from(document.querySelectorAll('.run-head strong')).find(
    (node) => node.textContent === artist,
  )
  const run = head?.closest('.run')
  return Array.from(run?.querySelectorAll('.trip-date .on') ?? []).map(
    (node) => node.textContent ?? '',
  )
}

describe('Favorites', () => {
  describe('the artists tab', () => {
    it('lists an artist’s dates without grouping them by country', async () => {
      await renderFeed()

      expect(bands()).toEqual([
        'Empire of the Sun',
        'Saint Levant',
        'Gorillaz',
        'System of a Down',
      ])
      expect(document.querySelectorAll('.favorite-place')).toHaveLength(0)
    })

    it('puts the town over the venue, and the country beside them', async () => {
      await renderFeed()

      const row = screen.getByText('Dos Equis Pavilion').closest<HTMLElement>('.show-row')!
      expect(within(row).getByText('Dallas, TX')).toBeInTheDocument()
      expect(within(row).getByText('United States of America')).toBeInTheDocument()
    })

    it('orders an artist’s dates chronologically', async () => {
      await renderFeed()

      const band = screen
        .getByRole('heading', { name: 'Empire of the Sun' })
        .closest<HTMLElement>('.favorite')!
      expect(
        Array.from(band.querySelectorAll('.show-row .day')).map((node) => node.textContent),
      ).toEqual(['20', '21', '24'])
    })

    it('shows no score, since it would be the same on every card', async () => {
      await renderFeed()

      expect(screen.queryAllByTestId('score-value')).toHaveLength(0)
    })

    it('collapses each artist, since ten of them is an index not a page', async () => {
      await renderFeed()

      const groups = document.querySelectorAll<HTMLDetailsElement>('details.favorite')
      expect(groups).toHaveLength(4)
      expect([...groups].every((group) => group.open)).toBe(false)
    })

    it('opens them under a filter, so the result is not hidden behind a click', async () => {
      await renderFeed()

      await tick(/United States/)

      const groups = document.querySelectorAll<HTMLDetailsElement>('details.favorite')
      expect(groups.length).toBeGreaterThan(0)
      expect([...groups].every((group) => group.open)).toBe(true)
    })

    it('does not offer a control on an artist with nothing to collapse', async () => {
      await renderFeed(makeFeed([{ name: 'Danheim', dates: [] }]))

      expect(document.querySelectorAll('details.favorite')).toHaveLength(0)
      expect(screen.getByText(/Nothing announced/)).toBeInTheDocument()
    })

    it('keeps the date count on the collapsed row, which is what it is for', async () => {
      await renderFeed()

      const group = screen
        .getByRole('heading', { name: 'Saint Levant' })
        .closest<HTMLElement>('.favorite')!
      expect(within(group).getByText('2 dates')).toBeInTheDocument()
    })

    it('offers no cluster controls, which mean nothing here', async () => {
      await renderFeed()

      expect(screen.queryByLabelText('Within')).toBeNull()
    })
  })

  describe('the trips tab', () => {
    it('groups a trip into consecutive runs per artist', async () => {
      await renderFeed()

      await trips()

      expect(runHeads()).toEqual([
        'Empire of the Sun',
        'Saint Levant',
        'Gorillaz',
        'System of a Down',
      ])
      expect(rowsUnder('Empire of the Sun')).toEqual([
        'Sun 20 Sep',
        'Mon 21 Sep',
        'Thu 24 Sep',
      ])
    })

    it('does not tack a date count onto a run heading', async () => {
      // the rows under it are the count
      await renderFeed()

      await trips()

      for (const head of document.querySelectorAll('.run-head')) {
        expect(head.textContent).not.toMatch(/date/)
      }
    })

    it('heads every run, including one of a single date', async () => {
      // a lone date with its act inline read as a different kind of thing
      // sitting among the blocks
      await renderFeed()

      await trips()

      expect(runHeads()).toContain('System of a Down')
      expect(document.querySelectorAll('.run.solo')).toHaveLength(0)
    })

    it('splits an act playing either side of another into two runs', async () => {
      await renderFeed(makeFeed(INTERLEAVED, TEXAS_CLUSTERS))

      await trips()

      expect(runHeads()).toEqual(['Empire of the Sun', 'Gorillaz', 'Empire of the Sun'])
    })

    it('names the trip by its span and place', async () => {
      await renderFeed()

      await trips()

      expect(bands()).toEqual(['20 Sep — 24 Oct 2026'])
    })

    it('labels a trip by its dates and nothing else', async () => {
      await renderFeed(
        makeFeed(TEXAS, [{ ...TEXAS_CLUSTERS[0], places: ['MA', 'NY', 'Canada'] }]),
      )

      await trips()

      expect(bands()).toEqual(['20 Sep — 24 Oct 2026'])
    })

    it('says how many favorites converge on the trip', async () => {
      await renderFeed()

      await trips()

      expect(
        screen.getByRole('heading', { name: /20 Sep/ }).parentElement,
      ).toHaveTextContent('4 favorites · 8 dates')
    })

    it('does not offer one act’s own tour leg as a trip', async () => {
      // you would not fly out to see the same band twice
      await renderFeed(makeFeed(SOLO_ACT, SOLO_CLUSTERS))

      await trips()

      expect(screen.getByText(/No trips/)).toBeInTheDocument()
      expect(screen.getByText(/widen the window or the radius/)).toBeInTheDocument()
    })

    it('leaves no explanatory note under the trips', async () => {
      await renderFeed(
        makeFeed(
          [
            ...TEXAS,
            { name: 'Danheim', dates: [{ date: '2026-12-01', city: 'Berlin', code: 'DE', cluster: 1 }] },
          ],
          [
            ...TEXAS_CLUSTERS,
            { id: 1, start_date: '2026-12-01', end_date: '2026-12-01', places: ['Germany'] },
          ],
        ),
      )

      await trips()

      expect(screen.queryByText(/sort by artist to see them/)).toBeNull()
      expect(document.querySelectorAll('.favorite-quiet')).toHaveLength(0)
    })

    it('hides the country filter, which is not how a trip is found', async () => {
      await renderFeed()

      await trips()

      expect(screen.queryByText('Countries')).toBeNull()
      expect(screen.queryByRole('checkbox', { name: /United States/ })).toBeNull()
    })

    it('exposes what counts as one trip, and re-asks when it changes', async () => {
      await renderFeed()
      const fetched = vi.mocked(api.favorites)

      await trips()
      fireEvent.change(screen.getByLabelText('Within'), { target: { value: '20' } })
      fireEvent.change(screen.getByLabelText('and'), { target: { value: '1200' } })

      await waitFor(() => {
        expect(fetched).toHaveBeenCalledWith({ days: 20, km: 650 })
        expect(fetched).toHaveBeenCalledWith({ days: 20, km: 1200 })
      })
    })

    it('clamps the trip shape to what the api will accept', async () => {
      await renderFeed()
      const fetched = vi.mocked(api.favorites)

      await trips()
      fireEvent.change(screen.getByLabelText('Within'), { target: { value: '900' } })

      await waitFor(() => expect(fetched).toHaveBeenCalledWith({ days: 60, km: 650 }))
    })

    it('goes back to artist bands when you switch back', async () => {
      await renderFeed()

      await trips()
      await artists()

      expect(bands()).toEqual([
        'Empire of the Sun',
        'Saint Levant',
        'Gorillaz',
        'System of a Down',
      ])
    })
  })

  describe('filters', () => {
    it('narrows to one artist', async () => {
      await renderFeed()

      await tick(/Gorillaz/)

      expect(bands()).toEqual(['Gorillaz'])
    })

    it('narrows to one country', async () => {
      await renderFeed(
        makeFeed(
          [
            ...TEXAS,
            { name: 'Danheim', dates: [{ date: '2026-12-01', city: 'Berlin', code: 'DE', cluster: 1 }] },
          ],
          TEXAS_CLUSTERS,
        ),
      )

      await tick(/Germany/)

      expect(bands()).toEqual(['Danheim'])
    })

    it('leaves an artist touring nowhere out of the artist filter', async () => {
      await renderFeed(makeFeed([...TEXAS, { name: 'Radiohead', dates: [] }], TEXAS_CLUSTERS))

      expect(screen.queryByRole('checkbox', { name: /Radiohead/ })).toBeNull()
    })

    it('counts dates against each country', async () => {
      await renderFeed()

      const us = screen.getByRole('checkbox', { name: /United States/ })
      expect(us.parentElement).toHaveTextContent(/United States of America\s*8/)
    })

    it('says when nothing clears them', async () => {
      await renderFeed(
        makeFeed(
          [
            ...TEXAS,
            { name: 'Danheim', dates: [{ date: '2026-12-01', city: 'Berlin', code: 'DE', cluster: 1 }] },
          ],
          TEXAS_CLUSTERS,
        ),
      )

      await tick(/Germany/)
      await tick(/Gorillaz/)

      expect(screen.getByText('Nothing clears these filters.')).toBeInTheDocument()
    })
  })

  it('still gives a favorite with nothing announced a row when unfiltered', async () => {
    await renderFeed(makeFeed([{ name: 'Empire of the Sun', dates: [] }]))

    expect(bands()).toEqual(['Empire of the Sun'])
    expect(
      screen.getByText(/Nothing announced anywhere before 2027-03-08/),
    ).toBeInTheDocument()
  })

  it('distinguishes not having looked yet from nothing being on', async () => {
    await renderFeed(makeFeed([{ name: 'Danheim', dates: [], searching: true }]))

    expect(screen.getByText(/Still looking/)).toBeInTheDocument()
    expect(screen.queryByText(/Nothing announced/)).toBeNull()
  })

  it('says when an artist is only still here on the follow window', async () => {
    await renderFeed(makeFeed([{ ...TEXAS[0], slipped: true }], TEXAS_CLUSTERS))

    expect(screen.getByText('slipped out of your top 10')).toBeInTheDocument()
  })

  it('leaves no notes under the filters', async () => {
    await renderFeed()

    expect(document.querySelectorAll('.side-meta')).toHaveLength(0)
    expect(screen.queryByText(/searched to/)).toBeNull()
  })

  it('points at Lidarr when the library is empty', async () => {
    await renderFeed(makeFeed([]))

    expect(screen.getByText(/add an artist there/)).toBeInTheDocument()
  })

  it('keeps a date markable from the trip view, so it reaches the calendar', async () => {
    await renderFeed()

    await trips()

    expect(
      screen.getAllByRole('button', { name: 'mark as bought' }).length,
    ).toBeGreaterThan(0)
  })
})
