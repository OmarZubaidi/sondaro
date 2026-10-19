import { geoArea } from 'd3-geo'
import { describe, expect, it } from 'vitest'
import world from '../../public/world.json'
import type { World } from './world'

const shapes = world as World

describe('world.json', () => {
  it('winds every country the way d3 reads it, so none fills the globe instead', () => {
    // a ring wound backwards reads as everything *but* the country: more than
    // half the sphere, where no real country comes close
    const inverted = Object.entries(shapes).filter(
      ([, polygons]) =>
        geoArea({ type: 'MultiPolygon', coordinates: polygons }) >= 2 * Math.PI,
    )
    expect(inverted.map(([code]) => code)).toEqual([])
  })

  it('has the countries trips most often name', () => {
    for (const code of ['US', 'CA', 'GB', 'IE', 'FR', 'DE', 'ES', 'NL', 'JP', 'KR', 'AU']) {
      expect(shapes[code], code).toBeDefined()
    }
  })
})
