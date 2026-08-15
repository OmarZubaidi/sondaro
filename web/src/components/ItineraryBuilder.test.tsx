import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ItineraryBuilder, buildLegs } from './ItineraryBuilder'
import type { Show } from '../lib/types'

function show(id: string, date: string, city: string, lat: number, lon: number): Show {
  return {
    id,
    artist: `Band ${id}`,
    listens: 100,
    score: 0.5,
    affinity: 0.5,
    date_fit: 1,
    reach_fit: 1,
    flags: [],
    reasons: [],
    drive_hours: null,
    miles: null,
    date,
    time: '20:00',
    venue: `${city} Hall`,
    city,
    region: null,
    country: 'FR',
    lat,
    lon,
    url: null,
    provider: 'ticketmaster',
  }
}

const LYON = show('a', '2026-09-08', 'Lyon', 45.764, 4.8357)
const GENEVA = show('b', '2026-09-09', 'Geneva', 46.2044, 6.1432)
const BARCELONA = show('c', '2026-09-10', 'Barcelona', 41.3874, 2.1686)
const BERLIN = show('d', '2026-09-09', 'Berlin', 52.52, 13.405)

describe('buildLegs', () => {
  it('orders picks by date regardless of selection order', () => {
    const legs = buildLegs([BARCELONA, LYON, GENEVA])
    expect(legs.map((l) => l.to.city)).toEqual(['Geneva', 'Barcelona'])
  })

  it('measures the distance between consecutive nights', () => {
    const [leg] = buildLegs([LYON, GENEVA])
    // Lyon to Geneva is ~112km / ~70mi as the crow flies
    expect(leg.miles).toBeGreaterThan(65)
    expect(leg.miles).toBeLessThan(75)
    expect(leg.severity).toBe('fine')
  })

  it('flags a jump that is not physically sensible', () => {
    const [leg] = buildLegs([LYON, BERLIN])
    expect(leg.severity).not.toBe('fine')
  })

  it('is more forgiving when there are nights in between', () => {
    const later = { ...BERLIN, date: '2026-09-15' }
    const [tight] = buildLegs([LYON, BERLIN])
    const [loose] = buildLegs([LYON, later])
    expect(loose.severity).toBe('fine')
    expect(tight.severity).not.toBe('fine')
  })

  it('skips legs where a venue has no coordinates', () => {
    const noCoords = { ...GENEVA, lat: null, lon: null }
    expect(buildLegs([LYON, noCoords])).toHaveLength(0)
  })
})

describe('ItineraryBuilder', () => {
  it('invites you to pick rather than picking for you', () => {
    render(<ItineraryBuilder picks={[]} onRemove={() => {}} />)
    expect(screen.getByText(/nothing is chosen for you/i)).toBeInTheDocument()
  })

  it('summarises the trip it has been given', () => {
    render(<ItineraryBuilder picks={[LYON, GENEVA]} onRemove={() => {}} />)
    expect(screen.getByText('2 shows')).toBeInTheDocument()
    expect(screen.getByText(/mi of travel/)).toBeInTheDocument()
  })

  it('warns about an awkward jump without removing the option', () => {
    render(<ItineraryBuilder picks={[LYON, BERLIN]} onRemove={() => {}} />)

    expect(screen.getByText(/awkward jump/)).toBeInTheDocument()
    expect(screen.getByText(/that is a flight/)).toBeInTheDocument()
    // both shows are still listed — nothing is hidden
    expect(screen.getByText('Band a')).toBeInTheDocument()
    expect(screen.getByText('Band d')).toBeInTheDocument()
  })

  it('does not warn about a sensible hop', () => {
    render(<ItineraryBuilder picks={[LYON, GENEVA]} onRemove={() => {}} />)
    expect(screen.queryByText(/awkward jump/)).not.toBeInTheDocument()
  })
})
