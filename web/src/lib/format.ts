import type { Show } from './types'

/* The API sends YYYY-MM-DD; the pages show "Sat 03 Apr". Parsed by hand
 * rather than through Intl, so the output doesn't depend on the browser's
 * locale or timezone. Uppercase is left to the stylesheet. */

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function weekdayIndex(iso: string): number {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

export function isWeekend(iso: string): boolean {
  const day = weekdayIndex(iso)
  return day === 5 || day === 6
}

export function dayNumber(iso: string): string {
  return iso.slice(8, 10)
}

export function weekdayShort(iso: string): string {
  return WEEKDAYS[weekdayIndex(iso)]
}

export function monthShort(iso: string): string {
  return MONTHS[Number(iso.slice(5, 7)) - 1]
}

export function monthYear(iso: string): string {
  return `${monthShort(iso)} ${iso.slice(0, 4)}`
}

/** "Sat 03 Apr" */
export function dateLabel(iso: string): string {
  return `${weekdayShort(iso)} ${dayNumber(iso)} ${monthShort(iso)}`
}

/** "02 — 14 Apr 2027", naming only what changes between the two ends. */
export function dateSpan(
  start: string,
  end: string,
  { year = true }: { year?: boolean } = {},
): string {
  const tail = (iso: string) => (year ? ` ${iso.slice(0, 4)}` : '')
  const dayMonth = (iso: string) => `${dayNumber(iso)} ${monthShort(iso)}`

  if (start === end) return `${dayMonth(start)}${tail(start)}`
  if (start.slice(0, 4) !== end.slice(0, 4))
    return `${dayMonth(start)}${tail(start)} — ${dayMonth(end)}${tail(end)}`
  if (start.slice(0, 7) === end.slice(0, 7))
    return `${dayNumber(start)} — ${dayMonth(end)}${tail(end)}`
  return `${dayMonth(start)} — ${dayMonth(end)}${tail(end)}`
}

/** Drive time is the metric that decides reachability, so it's rendered as
 *  hours and minutes rather than a decimal nobody reads. */
export function driveTime(show: Pick<Show, 'drive_hours' | 'flags'>): string | null {
  if (show.drive_hours === null) return null
  const hours = Math.floor(show.drive_hours)
  const minutes = Math.round((show.drive_hours - hours) * 60)
  const base = hours > 0 ? `${hours}h${minutes ? ` ${minutes}m` : ''}` : `${minutes}m`
  return show.flags.includes('estimated drive time') ? `~${base}` : base
}

/** `country: false` for a list already grouped by country, where the code
 *  would only repeat the heading. The region survives it — under "United
 *  States", "Fairview, KS" is the useful line and "Fairview" is ambiguous. */
export function place(
  show: Pick<Show, 'venue' | 'city' | 'region' | 'country'>,
  { country = true }: { country?: boolean } = {},
): string {
  const tail = country ? show.region ?? show.country : show.region
  return [show.venue, show.city, tail].filter(Boolean).join(', ')
}

/** The place as two lines, town first and venue under it, for a row whose
 *  heading already names the act. */
export function placeParts(
  show: Pick<Show, 'venue' | 'city' | 'region' | 'country'>,
  { country = true }: { country?: boolean } = {},
): { title: string; sub: string | null } {
  const tail = country ? show.region ?? show.country : show.region
  const town = [show.city, tail].filter(Boolean).join(', ')
  if (show.city || !show.venue) {
    return { title: town || 'venue to be announced', sub: show.venue }
  }
  return { title: show.venue, sub: town || null }
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

export function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 90) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 36) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
