/** Country shapes for the maps: alpha-2 -> polygons -> rings -> [lon, lat].
 *  Built by `scripts/build_borders.py --world`, wound the way d3-geo reads. */
export type World = Record<string, number[][][][]>

let pending: Promise<World> | null = null

/** Fetched once for every map on the page. A failure isn't remembered, so the
 *  next map to ask tries again, and meanwhile maps draw without land. */
export function loadWorld(): Promise<World> {
  pending ??= fetch('/world.json')
    .then((response) => {
      if (!response.ok) throw new Error(`world.json: ${response.status}`)
      return response.json() as Promise<World>
    })
    .catch(() => {
      pending = null
      return {}
    })
  return pending
}
