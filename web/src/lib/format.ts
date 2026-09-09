import type { Show } from './types'

/* Dates are rendered as the YYYY-MM-DD the API already sends: sortable,
 * unambiguous, and the same width everywhere — which matters on a page that is
 * mostly a column of them. There is nothing left to format, so there is no
 * formatter; the day of the week survives as `isWeekend`, which is the part of
 * it that changes a decision. */

export function isWeekend(iso: string): boolean {
  const day = new Date(`${iso}T12:00:00`).getDay()
  return day === 5 || day === 6
}

/** The hours a show occupies: `20:00 – 23:00`, or `20:00 – ~23:00` when the
 *  end is the assumed set length rather than a published one. A start on its
 *  own answers "when do I leave"; only the pair answers "am I driving home at
 *  one in the morning", which is the question that decides a weeknight.
 *
 *  Null when the doors are still TBA — there is nothing to bracket. The end
 *  date is shown only when it isn't the start date, which the API decides. */
export function timeRange(
  show: Pick<Show, 'time' | 'end_time' | 'end_date' | 'end_estimated'>,
): string | null {
  if (!show.time) return null
  if (!show.end_time) return show.time
  const day = show.end_date ? `${show.end_date} ` : ''
  return `${show.time} – ${day}${show.end_estimated ? '~' : ''}${show.end_time}`
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
