import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RouteMap, type MapStop } from './RouteMap'
import { loadWorld, type World } from '../lib/world'

vi.mock('../lib/world', () => ({ loadWorld: vi.fn() }))

// two boxes standing in for Japan and South Korea, wound clockwise as d3 reads
const box = (west: number, south: number, east: number, north: number) => [
  [
    [
      [west, south],
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ],
  ],
]
const WORLD: World = { JP: box(129, 31, 142, 42), KR: box(126, 34, 130, 38.5) }

const TOKYO: MapStop = { key: 'tokyo', lat: 35.68, lon: 139.69, tag: 'Tokyo 1', named: true }
const OSAKA: MapStop = { key: 'osaka', lat: 34.69, lon: 135.5, tag: 'Osaka 2', named: true }
const SEOUL: MapStop = { key: 'seoul', lat: 37.57, lon: 126.98, tag: 'Seoul 2', unplanned: true }
const LABEL = 'Route: Tokyo, then Osaka, then anywhere in South Korea'

const all = (selector: string) => document.querySelectorAll(selector)

beforeEach(() => {
  vi.mocked(loadWorld).mockResolvedValue(WORLD)
})

describe('RouteMap', () => {
  it('draws a trip: land, the route, pins, rings and tags', async () => {
    render(<RouteMap label={LABEL} stops={[TOKYO, OSAKA, SEOUL]} loose={['KR']} reachKm={240} />)

    expect(await screen.findByRole('img', { name: LABEL })).toBeInTheDocument()
    expect(all('.map-land')).toHaveLength(2)
    expect(all('.map-pin')).toHaveLength(3)
    expect(all('.map-pin.named')).toHaveLength(2)
    expect(all('.map-ring')).toHaveLength(2)
    expect([...all('.map-tag text')].map((t) => t.textContent)).toEqual([
      'Tokyo 1',
      'Osaka 2',
      'Seoul 2',
    ])
  })

  it('dashes the way into a stop that isn’t planned', async () => {
    render(<RouteMap label={LABEL} stops={[TOKYO, OSAKA, SEOUL]} />)

    await screen.findByRole('img')
    const legs = [...all('.map-route')]
    expect(legs).toHaveLength(2)
    expect(legs.map((leg) => leg.classList.contains('unplanned'))).toEqual([false, true])
  })

  it('fills a country with no city named in lavender', async () => {
    render(<RouteMap label={LABEL} stops={[TOKYO]} loose={['KR']} />)

    await screen.findByRole('img')
    expect(all('.map-loose')).toHaveLength(1)
  })

  it('pins a place visited twice once, and still draws both legs', async () => {
    render(<RouteMap label={LABEL} stops={[TOKYO, OSAKA, TOKYO]} />)

    await screen.findByRole('img')
    expect(all('.map-pin')).toHaveLength(2)
    expect(all('.map-route')).toHaveLength(2)
  })

  it('fits each tag’s text to its box, whatever font it ends up in', async () => {
    render(<RouteMap label={LABEL} stops={[TOKYO]} />)

    await screen.findByRole('img')
    const text = document.querySelector('.map-tag text')!
    const rect = document.querySelector('.map-tag rect')!
    expect(Number(text.getAttribute('textLength'))).toBeGreaterThan(0)
    expect(Number(rect.getAttribute('width'))).toBe(Number(text.getAttribute('textLength')) + 16)
  })

  it('still draws the route when the shapes can’t be loaded', async () => {
    vi.mocked(loadWorld).mockResolvedValue({})
    render(<RouteMap label={LABEL} stops={[TOKYO, OSAKA]} loose={['KR']} />)

    await screen.findByRole('img')
    expect(all('.map-land')).toHaveLength(0)
    expect(all('.map-loose')).toHaveLength(0)
    expect(all('.map-pin')).toHaveLength(2)
  })

  it('draws nothing when there is nothing to place', () => {
    render(<RouteMap label={LABEL} stops={[]} />)

    expect(document.querySelector('.route-map')).toBeNull()
  })

  it('draws nothing for a country too small to have a shape and no stops in it', async () => {
    render(<RouteMap label={LABEL} stops={[]} loose={['SG']} />)

    await waitFor(() => expect(loadWorld).toHaveBeenCalled())
    await waitFor(() => expect(document.querySelector('.route-map')).toBeNull())
  })
})
