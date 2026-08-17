export interface Show {
  id: string
  artist: string
  listens: number
  score: number
  affinity: number
  date_fit: number
  reach_fit: number
  flags: string[]
  reasons: string[]
  drive_hours: number | null
  miles: number | null
  date: string
  time: string | null
  venue: string | null
  city: string | null
  region: string | null
  country: string | null
  lat: number | null
  lon: number | null
  url: string | null
  provider: string
  purchased: boolean
  /** which trips this show turned up for; absent on the local feed */
  trips?: { id: number; name: string }[]
}

export interface Quota {
  provider: string
  window_days: number
  window_start: string
  used: number
  cap: number
  remaining: number
  fraction: number
  exhausted: boolean
}

export interface Status {
  home: { lat: number; lon: number; label: string }
  horizon_days: number
  coverage: number
  reindexing: boolean
  queue: Record<string, { total: number; due: number }>
  stalled: { task: string; error: string; failures: number }[]
  quotas: Quota[]
  providers: Record<string, boolean>
  library: {
    artists: number
    synced_at: string | null
    affinity_source: string
  }
  events_cached: number
  routing_host: string | null
  sweep_notes: string[]
  worker: { running: boolean; processed: number; last_error: string | null }
  alerts: { threshold: number; muted: boolean; mute_until: string }
  degraded: string[]
}

/** One country of a trip, optionally narrowed to a city and to dates.
 *  A country with no city is one you're going to but haven't planned. */
export interface TripLeg {
  country: string
  city: string | null
  start_date: string | null
  end_date: string | null
}

export interface Trip {
  id: number
  name: string
  legs: TripLeg[]
  countries: string[]
  cities: string[]
  start_date: string
  end_date: string
  flex_before: number
  flex_after: number
  strict_dates: boolean
  scanned_at: string | null
}

/** A country a trip touches, whether or not it turned anything up. One that
 *  found nothing gets a row reading zero rather than being left out — that
 *  absence is exactly what needed explaining. */
export interface TripCountry {
  code: string
  name: string
  /** sweeps for it are still queued, so zero may not be the final answer */
  searching: boolean
  /** why it will stay empty no matter how long you wait */
  note: string | null
}

/** Every trip and everything they turned up, in one feed. */
export interface TripsFeed {
  trips: Trip[]
  total: number
  dates: { date: string; shows: Show[] }[]
  countries: TripCountry[]
}

export interface CitySuggestion {
  name: string
  label: string
  country: string
  lat: number
  lon: number
}

export interface LocalFeed {
  total: number
  months: { label: string; shows: Show[] }[]
  status: Status
}

export interface SettingSpec {
  key: string
  label: string
  kind: 'float' | 'int' | 'str' | 'bool' | 'date'
  value: string | number | boolean
  minimum: number | null
  maximum: number | null
  help: string
}

export interface SettingsPayload {
  settings: SettingSpec[]
  credentials: Record<string, boolean>
  quotas: Quota[]
}
