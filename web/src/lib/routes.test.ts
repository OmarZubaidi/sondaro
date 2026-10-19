import { describe, expect, it } from 'vitest'
import { clusterMap, haversineKm, tripMap } from './routes'
import type { Show, Trip } from './types'

const AT: Record<string, [number, number]> = {
  Tokyo: [35.68, 139.69],
  Osaka: [34.69, 135.5],
  Seoul: [37.57, 126.98],
  'New York': [40.71, -74.0],
  Queens: [40.73, -73.79],
  Philadelphia: [39.95, -75.17],
  Boston: [42.36, -71.06],
  Dublin: [53.35, -6.26],
  Glasgow: [55.86, -4.25],
}

let n = 0
function show(city: string, country: string, date: string, extra: Partial<Show> = {}): Show {
  const [lat, lon] = AT[city]
  return {
    id: `s${++n}`,
    artist: 'Someone',
    listens: 1,
    score: 0.5,
    affinity: 0.5,
    date_fit: 1,
    reach_fit: 1,
    flags: [],
    reasons: [],
    drive_hours: null,
    km: null,
    date,
    time: null,
    venue: `${city} Hall`,
    city,
    region: null,
    country,
    lat,
    lon,
    url: null,
    provider: 'ticketmaster',
    purchased: false,
    ...extra,
  }
}

function trip(legs: Trip['legs'], placed: string[]): Trip {
  return {
    id: 1,
    name: 'A trip',
    legs,
    countries: [...new Set(legs.map((leg) => leg.country))],
    cities: legs.flatMap((leg) => (leg.city ? [leg.city] : [])),
    places: placed.map((city) => {
      const leg = legs.find((l) => l.city === city)!
      return { city, country: leg.country, lat: AT[city][0], lon: AT[city][1] }
    }),
    start_date: '2027-04-02',
    end_date: '2027-04-14',
    flex_before: 0,
    flex_after: 0,
    strict_dates: false,
    scanned_at: null,
  }
}

const NAMES = new Map([['KR', 'South Korea']])

describe('tripMap', () => {
  const japan = trip(
    [
      { country: 'JP', city: 'Tokyo', start_date: '2027-04-02', end_date: '2027-04-07' },
      { country: 'JP', city: 'Osaka', start_date: '2027-04-08', end_date: '2027-04-12' },
      { country: 'KR', city: null, start_date: null, end_date: null },
    ],
    ['Tokyo', 'Osaka'],
  )
  const japanShows = [
    show('Tokyo', 'JP', '2027-04-03'),
    show('Osaka', 'JP', '2027-04-09'),
    show('Osaka', 'JP', '2027-04-09'),
    show('Seoul', 'KR', '2027-04-13'),
    show('Seoul', 'KR', '2027-04-15'),
  ]

  it('follows the legs, and leaves a country with no city open', () => {
    const plan = tripMap(japan, japanShows, NAMES)

    expect(plan.stops.map((s) => [s.tag, !!s.named, !!s.unplanned])).toEqual([
      ['Tokyo 1', true, false],
      ['Osaka 2', true, false],
      ['Seoul 2', false, true],
    ])
    expect(plan.loose).toEqual(['KR'])
    expect(plan.nearby).toEqual([])
    expect(plan.label).toBe('Route: Tokyo, then Osaka, then anywhere in South Korea')
  })

  it('counts a show in the metro as in the city, and pins the rest off the route', () => {
    const newYork = trip(
      [{ country: 'US', city: 'New York', start_date: '2027-05-14', end_date: '2027-05-20' }],
      ['New York'],
    )
    const plan = tripMap(
      newYork,
      [
        show('Queens', 'US', '2027-05-15'),
        show('New York', 'US', '2027-05-18'),
        show('Philadelphia', 'US', '2027-05-19'),
        show('Boston', 'US', '2027-05-20'),
      ],
      NAMES,
    )

    expect(plan.stops.map((s) => s.tag)).toEqual(['New York 2'])
    expect(plan.nearby.map((s) => s.tag)).toEqual(['Philadelphia 1', 'Boston 1'])
    expect(plan.label).toBe('Route: New York, with shows nearby in Philadelphia and Boston')
  })

  it('dashes the way into a named city that has no dates yet', () => {
    const undated = trip(
      [
        { country: 'JP', city: 'Tokyo', start_date: '2027-04-02', end_date: '2027-04-07' },
        { country: 'JP', city: 'Osaka', start_date: null, end_date: null },
      ],
      ['Tokyo', 'Osaka'],
    )

    expect(tripMap(undated, [], NAMES).stops.map((s) => !!s.unplanned)).toEqual([false, true])
  })

  it('leaves out a city that hasn’t been geocoded, rather than guessing', () => {
    const plan = tripMap({ ...japan, places: japan.places.slice(0, 1) }, [], NAMES)

    expect(plan.stops.map((s) => s.tag)).toEqual(['Tokyo'])
    expect(plan.label).toBe('Route: Tokyo, then anywhere in South Korea')
  })

  it('ignores a show it has no coordinates for', () => {
    const plan = tripMap(japan, [show('Tokyo', 'JP', '2027-04-03', { lat: null, lon: null })], NAMES)

    expect(plan.stops[0].tag).toBe('Tokyo')
  })
})

describe('clusterMap', () => {
  it('goes city to city in date order, tagging each with its days', () => {
    const plan = clusterMap([
      show('Glasgow', 'GB', '2027-02-14'),
      show('Dublin', 'IE', '2027-02-12'),
      show('Glasgow', 'GB', '2027-02-15'),
      show('Dublin', 'IE', '2027-02-17'),
    ])

    expect(plan.stops.map((s) => s.tag)).toEqual(['Dublin 12 · 17', 'Glasgow 14 · 15', 'Dublin 12 · 17'])
    expect(plan.stops.every((s) => s.named && !s.unplanned)).toBe(true)
    expect(plan.label).toBe('Route: Dublin, then Glasgow, then Dublin')
  })
})

describe('haversineKm', () => {
  it('measures New York to Philadelphia at about 130km', () => {
    expect(haversineKm(...AT['New York'], ...AT.Philadelphia)).toBeCloseTo(130, -1)
  })
})
