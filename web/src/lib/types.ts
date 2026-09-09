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
  km: number | null
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
  /** which detected cluster this date falls in; only on the favorites feed */
  cluster?: number | null
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

/** One country a favourite plays, and the dates they play there. */
export interface FavoriteCountry {
  code: string
  name: string
  shows: Show[]
}

/** A favourite and everywhere they're playing, anywhere on earth. */
export interface FavoriteArtist {
  key: string
  name: string
  listens: number
  affinity: number
  /** no clean worldwide lookup yet, so no dates isn't the answer */
  searching: boolean
  /** still here on the follow window rather than on current rank */
  slipped: boolean
  total: number
  countries: FavoriteCountry[]
}

/** A run of dates close enough in time and space to be one trip. Computed
 *  server-side across every favourite at once, since the whole point is the
 *  week several of them overlap. */
export interface Cluster {
  id: number
  start_date: string
  end_date: string
  /** country names, or state codes inside countries too big to name usefully.
   *  Nothing renders these now that a trip is labelled by its dates alone. */
  places: string[]
}

export interface FavoritesFeed {
  artists: FavoriteArtist[]
  clusters: Cluster[]
  total: number
  /** the `favorite_artists` setting. `artists` runs longer whenever someone is
   *  still inside their follow window. */
  follows: number
  /** what counted as one trip for this response */
  cluster_days: number
  cluster_km: number
  /** how far ahead the worldwide lookups reach; a blank past it means we
   *  haven't looked, not that nothing is on */
  searched_to: string
  countries: { code: string; name: string }[]
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
  /** where this app answers from off the LAN. Empty when it couldn't be
   *  worked out — see `config.tailnet_url`. */
  tailnet_url: string
}
