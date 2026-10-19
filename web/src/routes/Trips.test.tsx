import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Trips } from './Trips'
import { api } from '../lib/api'
import type { Show, Trip, TripLeg, TripPlace, TripsFeed } from '../lib/types'

vi.mock('../lib/world', () => ({ loadWorld: () => Promise.resolve({}) }))

function show(
  id: string,
  artist: string,
  date: string,
  country: string,
  trips: number[],
  overrides: Partial<Show> = {},
): Show {
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
    drive_hours: null,
    km: null,
    date,
    time: '19:30',
    venue: `${artist} Hall`,
    city: 'Somewhere',
    region: null,
    country,
    lat: 0,
    lon: 0,
    url: null,
    provider: 'ticketmaster',
    purchased: false,
    trips: trips.map((tripId) => ({ id: tripId, name: NAMES[tripId] })),
    ...overrides,
  }
}

const NAMES: Record<number, string> = { 1: 'Spring tour', 2: 'New York', 3: 'Iceland' }

function trip(
  id: number,
  start: string,
  end: string,
  legs: TripLeg[],
  places: TripPlace[] = [],
): Trip {
  return {
    id,
    name: NAMES[id],
    legs,
    countries: [...new Set(legs.map((leg) => leg.country))],
    cities: legs.flatMap((leg) => (leg.city ? [leg.city] : [])),
    places,
    start_date: start,
    end_date: end,
    flex_before: 0,
    flex_after: 0,
    strict_dates: false,
    scanned_at: null,
  }
}

const TRIPS: Trip[] = [
  trip(
    1,
    '2027-04-02',
    '2027-04-14',
    [
      { country: 'JP', city: 'Tokyo', start_date: '2027-04-02', end_date: '2027-04-07' },
      { country: 'KR', city: null, start_date: null, end_date: null },
    ],
    [{ city: 'Tokyo', country: 'JP', lat: 35.68, lon: 139.69 }],
  ),
  trip(2, '2027-05-14', '2027-05-20', [
    { country: 'US', city: 'New York', start_date: '2027-05-14', end_date: '2027-05-20' },
  ]),
  trip(3, '2027-06-01', '2027-06-08', [
    { country: 'IS', city: null, start_date: null, end_date: null },
  ]),
]

const SHOWS: Show[] = [
  show('a', 'Mitski', '2027-04-03', 'JP', [1], { score: 0.7 }),
  // one show both trips want
  show('b', 'Khruangbin', '2027-04-05', 'JP', [1, 2]),
  show('c', 'Toe', '2027-04-09', 'JP', [1], { score: 0.55 }),
  show('d', 'Boris', '2027-04-09', 'JP', [1], { score: 0.4 }),
  // under the score floor, but bought
  show('e', 'Alvvays', '2027-05-18', 'US', [2], { score: 0.02, purchased: true }),
  // under the score floor
  show('f', 'Slowdive', '2027-05-19', 'US', [2], { score: 0.03 }),
]

function makeFeed(overrides: Partial<TripsFeed> = {}): TripsFeed {
  const byDate = new Map<string, Show[]>()
  for (const s of SHOWS) byDate.set(s.date, [...(byDate.get(s.date) ?? []), s])
  return {
    trips: TRIPS,
    city_reach_km: 240,
    total: SHOWS.length,
    dates: [...byDate].map(([date, shows]) => ({ date, shows })),
    countries: [
      { code: 'JP', name: 'Japan', searching: false, note: null },
      { code: 'US', name: 'United States', searching: false, note: null },
      { code: 'KR', name: 'South Korea', searching: true, note: null },
    ],
    ...overrides,
  }
}

async function renderTrips(feed: TripsFeed = makeFeed()) {
  vi.spyOn(api, 'trips').mockResolvedValue(feed)
  vi.spyOn(api, 'countries').mockResolvedValue({
    countries: [
      { code: 'JP', name: 'Japan' },
      { code: 'KR', name: 'South Korea' },
      { code: 'US', name: 'United States' },
      { code: 'IS', name: 'Iceland' },
    ],
  })
  render(<Trips />)
  await screen.findByRole('heading', { name: 'Your trips' })
}

const sections = () =>
  screen.getAllByRole('region').map((node) => node.getAttribute('aria-label'))
const section = (name: string) => screen.getByRole('region', { name })
const tick = (name: RegExp) => userEvent.click(screen.getByRole('checkbox', { name }))

describe('Trips', () => {
  it('gives every trip a section of its own, in order', async () => {
    await renderTrips()

    expect(sections()).toEqual(['Spring tour', 'New York', 'Iceland'])
    expect(
      within(section('Spring tour')).getByRole('heading', { name: 'Spring tour' }),
    ).toBeInTheDocument()
    expect(within(section('Spring tour')).getByText('02 — 14 Apr 2027')).toBeInTheDocument()
  })

  it('maps each trip from its legs', async () => {
    await renderTrips()

    expect(
      await within(section('Spring tour')).findByRole('img', {
        name: /^Route: Tokyo, then anywhere in South Korea/,
      }),
    ).toBeInTheDocument()
  })

  it('lists the legs, and a country with no city as anywhere, any day', async () => {
    await renderTrips()

    const spring = section('Spring tour')
    expect(within(spring).getByText('Tokyo')).toBeInTheDocument()
    expect(within(spring).getByText('02 — 07 Apr')).toBeInTheDocument()
    expect(await within(spring).findByText('South Korea')).toBeInTheDocument()
    expect(within(spring).getByText('anywhere, any day')).toBeInTheDocument()
  })

  it('puts a show under every trip that wants it', async () => {
    await renderTrips()

    expect(within(section('Spring tour')).getByText('Khruangbin')).toBeInTheDocument()
    expect(within(section('New York')).getByText('Khruangbin')).toBeInTheDocument()
  })

  it('groups a trip’s shows by date', async () => {
    await renderTrips()

    const spring = section('Spring tour')
    expect(
      within(spring)
        .getAllByRole('heading', { level: 3 })
        .map((node) => node.textContent),
    ).toEqual(['Sat 03 Apr', 'Mon 05 Apr', 'Fri 09 Apr · 2 options'])
  })

  it('counts each show once, however many trips want it', async () => {
    await renderTrips()

    // six shows, one of them under the score floor
    expect(screen.getByText('5 of 6 shown')).toBeInTheDocument()
    expect(screen.getByText('3 trips')).toBeInTheDocument()
  })

  it('hides anything under the score floor, unless you are going', async () => {
    await renderTrips()

    expect(screen.queryByText('Slowdive')).toBeNull()
    expect(within(section('New York')).getByText('Alvvays')).toBeInTheDocument()
  })

  it('narrows to the trips you tick', async () => {
    await renderTrips()

    await tick(/^New York/)

    expect(sections()).toEqual(['New York'])
  })

  it('keeps a trip with a show you are going to, even when it is not ticked', async () => {
    await renderTrips()

    await tick(/^Spring tour/)

    expect(sections()).toEqual(['Spring tour', 'New York'])
    const newYork = section('New York')
    expect(within(newYork).getByText('Alvvays')).toBeInTheDocument()
    expect(within(newYork).queryByText('Khruangbin')).toBeNull()
  })

  it('says when the filters empty a trip that did find something', async () => {
    await renderTrips()

    await tick(/^United States/)

    expect(
      within(section('Spring tour')).getByText('Nothing clears these filters.'),
    ).toBeInTheDocument()
    // Iceland never found anything, so there is nothing for a filter to explain
    expect(within(section('Iceland')).queryByText(/Nothing clears/)).toBeNull()
  })

  it('says under a country why it is still empty', async () => {
    await renderTrips()

    expect(
      screen.getByText('Still being searched, so this may not be the final answer.'),
    ).toBeInTheDocument()
  })

  it('deletes a trip from its own header, once confirmed', async () => {
    await renderTrips()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const deleted = vi.spyOn(api, 'deleteTrip').mockResolvedValue(undefined)

    await userEvent.click(screen.getByRole('button', { name: 'Delete New York' }))

    expect(deleted).toHaveBeenCalledWith(2)
    expect(screen.getByRole('button', { name: 'Edit New York' })).toBeInTheDocument()
  })

  it('says how to start when there are no trips', async () => {
    await renderTrips(makeFeed({ trips: [], dates: [], total: 0, countries: [] }))

    expect(screen.getByText(/No trips yet/)).toBeInTheDocument()
  })
})
