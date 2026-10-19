import { useEffect, useState } from 'react'
import { geoCircle, geoMercator, geoPath } from 'd3-geo'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { loadWorld, type World } from '../lib/world'

export interface MapStop {
  /** the same key twice is one place visited twice: one pin, two legs */
  key: string
  lat: number
  lon: number
  /** "Tokyo 1": the place, and whatever count or days belong beside it */
  tag: string
  /** a city you named: a fuchsia pin, ringed at its reach. Otherwise white. */
  named?: boolean
  /** the way into this stop isn't planned yet, so it's drawn dashed */
  unplanned?: boolean
}

export interface RouteMapProps {
  /** what the map shows, for anyone who can't see it */
  label: string
  /** in route order; each one is joined to the one before it */
  stops: MapStop[]
  /** ISO-2 countries in play with no city named */
  loose?: string[]
  /** the ring around each named city */
  reachKm?: number
}

const WIDTH = 360
const HEIGHT = 270
const PAD = 30
const KM_PER_DEGREE = 111.32
// a stop without a ring still needs some ground around it to frame
const FRAME_KM = 120
const TAG_HEIGHT = 26
const TAG_PAD = 8
const NARROW = new Set([' ', '.', '·', ':', ',', "'", '1', 'I', '-'])

/** Roughly how wide a tag sets in Anton at 17px, uppercase. The text is then
 *  fitted to exactly this with `textLength`, so a font still loading, or a
 *  fallback, can't spill out of its box. */
function tagWidth(text: string): number {
  return [...text.toUpperCase()].reduce((sum, c) => sum + (NARROW.has(c) ? 4.6 : 9.2), 0)
}

const feature = (geometry: Geometry): Feature => ({ type: 'Feature', properties: {}, geometry })

const circle = (lon: number, lat: number, km: number) =>
  feature(geoCircle().center([lon, lat]).radius(km / KM_PER_DEGREE)())

function country(world: World, code: string): Feature | null {
  const polygons = world[code.toUpperCase()]
  return polygons ? feature({ type: 'MultiPolygon', coordinates: polygons }) : null
}

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high)

/** A gentle curve rather than a ruler line, bowed to one side. */
function bend(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  return `M${x1},${y1} Q${mx - (y2 - y1) * 0.18},${my + (x2 - x1) * 0.18} ${x2},${y2}`
}

function draw(world: World, stops: MapStop[], loose: string[], reachKm?: number) {
  const looseShapes = loose.flatMap((code) => {
    const shape = country(world, code)
    return shape ? [{ code, shape }] : []
  })
  const frame: FeatureCollection = {
    type: 'FeatureCollection',
    features: [
      ...stops.map((s) => circle(s.lon, s.lat, s.named && reachKm ? reachKm : FRAME_KM)),
      ...looseShapes.map((l) => l.shape),
    ],
  }
  if (frame.features.length === 0) return null

  const projection = geoMercator()
    .fitExtent(
      [
        [PAD, PAD],
        [WIDTH - PAD, HEIGHT - PAD],
      ],
      frame,
    )
    .clipExtent([
      [0, 0],
      [WIDTH, HEIGHT],
    ])
  const path = geoPath(projection)
  const at = (s: MapStop) => projection([s.lon, s.lat]) ?? [0, 0]

  const land = Object.keys(world)
    .map((code) => ({ code, d: path(country(world, code)!) ?? '' }))
    .filter((shape) => shape.d)

  const route = stops.slice(1).flatMap((stop, i) => {
    const [x1, y1] = at(stops[i])
    const [x2, y2] = at(stop)
    if (Math.hypot(x2 - x1, y2 - y1) < 1) return []
    return [{ key: `${i}:${stops[i].key}>${stop.key}`, d: bend(x1, y1, x2, y2), unplanned: stop.unplanned }]
  })

  const pins = stops
    .filter((stop, i) => stops.findIndex((s) => s.key === stop.key) === i)
    .map((stop) => {
      const [x, y] = at(stop)
      const width = tagWidth(stop.tag)
      const box = width + TAG_PAD * 2
      const right = x + 14
      return {
        ...stop,
        x,
        y,
        width,
        tagX: clamp(right + box > WIDTH - 2 ? x - 14 - box : right, 2, WIDTH - 2 - box),
        tagY: clamp(y + 8, 2, HEIGHT - 2 - TAG_HEIGHT),
      }
    })

  return {
    land,
    loose: looseShapes.map((l) => ({ code: l.code, d: path(l.shape) ?? '' })),
    rings:
      reachKm === undefined
        ? []
        : pins
            .filter((pin) => pin.named)
            .map((pin) => ({ key: pin.key, d: path(circle(pin.lon, pin.lat, reachKm)) ?? '' })),
    route,
    pins,
  }
}

/** A trip's route over flat pink land, in the poster style of the rest of the
 *  site: no key, no tiles, nothing fetched but the one shapes file. */
export function RouteMap({ label, stops, loose = [], reachKm }: RouteMapProps) {
  const [world, setWorld] = useState<World | null>(null)

  useEffect(() => {
    let live = true
    loadWorld().then((shapes) => live && setWorld(shapes))
    return () => {
      live = false
    }
  }, [])

  if (stops.length === 0 && loose.length === 0) return null
  const drawing = world && draw(world, stops, loose, reachKm)
  if (world && !drawing) return null

  return (
    <div className="route-map">
      {drawing && (
        <svg
          role="img"
          aria-label={label}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="xMidYMid meet"
        >
          {drawing.land.map((shape) => (
            <path key={shape.code} className="map-land" d={shape.d} />
          ))}
          {drawing.loose.map((shape) => (
            <path key={shape.code} className="map-loose" d={shape.d} />
          ))}
          {drawing.rings.map((ring) => (
            <path key={ring.key} className="map-ring" d={ring.d} />
          ))}
          {drawing.route.map((leg) => (
            <path
              key={leg.key}
              className={`map-route${leg.unplanned ? ' unplanned' : ''}`}
              d={leg.d}
            />
          ))}
          {drawing.pins.map((pin) => (
            <circle
              key={pin.key}
              className={`map-pin${pin.named ? ' named' : ''}`}
              cx={pin.x}
              cy={pin.y}
              r={pin.named ? 10 : 9}
            />
          ))}
          {drawing.pins.map((pin) => (
            <g key={`${pin.key}-tag`} className="map-tag">
              <rect
                x={pin.tagX}
                y={pin.tagY}
                width={pin.width + TAG_PAD * 2}
                height={TAG_HEIGHT}
              />
              <text
                x={pin.tagX + TAG_PAD}
                y={pin.tagY + 19}
                textLength={pin.width}
                lengthAdjust="spacingAndGlyphs"
              >
                {pin.tag}
              </text>
            </g>
          ))}
        </svg>
      )}
    </div>
  )
}
