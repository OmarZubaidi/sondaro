const EARTH_RADIUS_MILES = 3958.8

export function haversineMiles(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180
  const p1 = toRad(lat1)
  const p2 = toRad(lat2)
  const dp = toRad(lat2 - lat1)
  const dl = toRad(lon2 - lon1)
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  return 2 * EARTH_RADIUS_MILES * Math.asin(Math.sqrt(Math.min(a, 1)))
}

/** Roughly what you can cover between two consecutive nights. Beyond this the
 *  itinerary is telling you something is physically awkward, not forbidding it. */
export const COMFORTABLE_HOP_MILES = 250
export const IMPLAUSIBLE_HOP_MILES = 600

export function hopSeverity(miles: number, nightsBetween: number): 'fine' | 'long' | 'implausible' {
  const budget = Math.max(nightsBetween, 1)
  if (miles <= COMFORTABLE_HOP_MILES * budget) return 'fine'
  if (miles <= IMPLAUSIBLE_HOP_MILES * budget) return 'long'
  return 'implausible'
}
