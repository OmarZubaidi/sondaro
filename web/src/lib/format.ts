import type { Show } from './types'

export function prettyDate(iso: string): string {
  const parsed = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

export function prettyDateLong(iso: string): string {
  const parsed = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return iso
  return parsed.toLocaleDateString(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

export function isWeekend(iso: string): boolean {
  const day = new Date(`${iso}T12:00:00`).getDay()
  return day === 5 || day === 6
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

export function place(show: Pick<Show, 'venue' | 'city' | 'region' | 'country'>): string {
  return [show.venue, show.city, show.region ?? show.country].filter(Boolean).join(', ')
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
