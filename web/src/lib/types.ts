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

export interface Trip {
  id: number
  name: string
  countries: string[]
  cities: string[]
  start_date: string
  end_date: string
  flex_before: number
  flex_after: number
  strict_dates: boolean
  scanned_at: string | null
}

export interface TripDetail {
  trip: Trip
  total: number
  dates: { date: string; shows: Show[] }[]
  coverage: number
  notes: string[]
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
  home_managed_by: string | null
}

export interface GeocodeResult {
  label: string
  lat: number
  lon: number
  country: string | null
}
