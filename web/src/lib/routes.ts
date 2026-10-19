import type { MapStop } from '../components/RouteMap'
import type { Show, Trip } from './types'
import { dayNumber } from './format'

/** What a map draws: the route, what's pinned off it, and the countries left
 *  open, plus a sentence saying the same for anyone who can't see it. */
export interface MapPlan {
  label: string
  stops: MapStop[]
  nearby: MapStop[]
  loose: string[]
}

// a show this close to a named city counts as in it: Queens is New York,
// Philadelphia is not
const METRO_KM = 50

type Located = Show & { lat: number; lon: number }

const located = (show: Show): show is Located => show.lat !== null && show.lon !== null

const byDate = (a: Show, b: Show) => a.date.localeCompare(b.date)

const cityOf = (show: Show) => show.city ?? show.venue ?? ''

const keyOf = (country: string | null, city: string) => `${country ?? ''}:${city.toLowerCase()}`

export function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180
  const a =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2
  return 2 * 6371 * Math.asin(Math.sqrt(a))
}

/** Shows grouped by the city they're in, in the order they first come up. */
function byCity(shows: Located[]): { key: string; city: string; shows: Located[] }[] {
  const groups: { key: string; city: string; shows: Located[] }[] = []
  for (const show of shows) {
    const key = keyOf(show.country, cityOf(show))
    const group = groups.find((g) => g.key === key)
    if (group) group.shows.push(show)
    else groups.push({ key, city: cityOf(show), shows: [show] })
  }
  return groups
}

const counted = (city: string, count: number) => (count ? `${city} ${count}` : city)

function sentence(parts: string[], nearby: string[]): string {
  const route = parts.length ? `Route: ${parts.join(', then ')}` : 'Shows'
  if (!nearby.length) return route
  const places =
    nearby.length === 1 ? nearby[0] : `${nearby.slice(0, -1).join(', ')} and ${nearby.at(-1)}`
  return `${route}, with shows nearby in ${places}`
}

/** A booked trip: its legs in order, each named city tagged with the shows
 *  around it, a country with no city named left open with its shows on a
 *  dotted line, and anything else pinned where it is, off the route. */
export function tripMap(trip: Trip, shows: Show[], countryNames: Map<string, string>): MapPlan {
  const ordered = shows.filter(located).sort(byDate)
  const claimed = new Set<string>()
  const stops: MapStop[] = []
  const loose: string[] = []
  const parts: string[] = []

  for (const leg of trip.legs) {
    if (leg.city) {
      const place = trip.places.find((p) => p.city === leg.city && p.country === leg.country)
      // not geocoded yet: there is nowhere honest to put it
      if (!place) continue
      const around = ordered.filter(
        (show) => haversineKm(show.lat, show.lon, place.lat, place.lon) <= METRO_KM,
      )
      around.forEach((show) => claimed.add(show.id))
      stops.push({
        key: keyOf(leg.country, leg.city),
        lat: place.lat,
        lon: place.lon,
        tag: counted(leg.city, around.length),
        named: true,
        unplanned: !leg.start_date,
      })
      parts.push(leg.city)
      continue
    }

    loose.push(leg.country)
    const inCountry = ordered.filter((show) => show.country === leg.country && !claimed.has(show.id))
    for (const group of byCity(inCountry)) {
      group.shows.forEach((show) => claimed.add(show.id))
      const [first] = group.shows
      stops.push({
        key: group.key,
        lat: first.lat,
        lon: first.lon,
        tag: counted(group.city, group.shows.length),
        unplanned: true,
      })
    }
    parts.push(`anywhere in ${countryNames.get(leg.country) ?? leg.country}`)
  }

  const rest = byCity(ordered.filter((show) => !claimed.has(show.id)))
  const nearby = rest.map((group) => ({
    key: group.key,
    lat: group.shows[0].lat,
    lon: group.shows[0].lon,
    tag: counted(group.city, group.shows.length),
  }))

  return {
    label: sentence(parts, rest.map((group) => group.city)),
    stops,
    nearby,
    loose,
  }
}

/** A could-be trip: the cities its dates fall in, in date order, each tagged
 *  with the days it plays there. Nothing on it is planned, so nothing is
 *  dashed: the line is just the order the dates come in. */
export function clusterMap(shows: Show[]): MapPlan {
  const ordered = shows.filter(located).sort(byDate)
  const days = new Map<string, string[]>()
  const stops: MapStop[] = []

  for (const show of ordered) {
    const key = keyOf(show.country, cityOf(show))
    const seen = days.get(key) ?? []
    if (!seen.includes(dayNumber(show.date))) seen.push(dayNumber(show.date))
    days.set(key, seen)
    if (stops.at(-1)?.key !== key) {
      stops.push({ key, lat: show.lat, lon: show.lon, tag: cityOf(show), named: true })
    }
  }

  return {
    label: sentence(
      stops.map((stop) => stop.tag),
      [],
    ),
    stops: stops.map((stop) => ({ ...stop, tag: `${stop.tag} ${days.get(stop.key)!.join(' · ')}` })),
    nearby: [],
    loose: [],
  }
}
