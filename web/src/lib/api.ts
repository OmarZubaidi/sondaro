import type {
  GeocodeResult,
  HomeFeed,
  SettingsPayload,
  Status,
  Trip,
  TripDetail,
} from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // response wasn't json; the status line is all we have
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  home: (opts: { minScore?: number; discovery?: boolean } = {}) => {
    const params = new URLSearchParams()
    if (opts.minScore !== undefined) params.set('min_score', String(opts.minScore))
    if (opts.discovery !== undefined) params.set('discovery', String(opts.discovery))
    const query = params.toString()
    return request<HomeFeed>(`/api/home${query ? `?${query}` : ''}`)
  },

  status: () => request<Status>('/api/status'),

  sync: () => request<{ artists: number }>('/api/sync', { method: 'POST' }),

  trips: () => request<{ trips: Trip[] }>('/api/trips'),

  trip: (id: number) => request<TripDetail>(`/api/trips/${id}`),

  createTrip: (payload: Record<string, unknown>) =>
    request<Trip>('/api/trips', { method: 'POST', body: JSON.stringify(payload) }),

  rescanTrip: (id: number) =>
    request<{ queued: number }>(`/api/trips/${id}/rescan`, { method: 'POST' }),

  deleteTrip: (id: number) =>
    request<void>(`/api/trips/${id}`, { method: 'DELETE' }),

  settings: () => request<SettingsPayload>('/api/settings'),

  updateSettings: (payload: Record<string, unknown>) =>
    request<{ updated: Record<string, unknown> }>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  setHome: (payload: { lat: number; lon: number; label?: string }) =>
    request<{ reindexing: boolean }>('/api/settings/home', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  geocode: (q: string) =>
    request<{ results: GeocodeResult[] }>(`/api/geocode?q=${encodeURIComponent(q)}`),

  countries: () =>
    request<{ countries: { code: string; name: string }[] }>('/api/countries'),
}
