import type {
  CitySuggestion,
  LocalFeed,
  SettingsPayload,
  Status,
  Trip,
  TripsFeed,
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
  home: (filters: Record<string, number> = {}) => {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null) params.set(key, String(value))
    }
    const query = params.toString()
    return request<LocalFeed>(`/api/local${query ? `?${query}` : ''}`)
  },

  status: () => request<Status>('/api/status'),

  sync: () => request<{ artists: number }>('/api/sync', { method: 'POST' }),

  trips: () => request<TripsFeed>('/api/trips'),

  createTrip: (payload: Record<string, unknown>) =>
    request<Trip>('/api/trips', { method: 'POST', body: JSON.stringify(payload) }),

  updateTrip: (id: number, payload: Record<string, unknown>) =>
    request<Trip & { rescanned: boolean; queued: number }>(`/api/trips/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

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

  countries: () =>
    request<{ countries: { code: string; name: string }[] }>('/api/countries'),

  cities: (q: string, countries: string[]) =>
    request<{ cities: CitySuggestion[] }>(
      `/api/cities?q=${encodeURIComponent(q)}&countries=${countries.join(',')}`,
    ),

  setPurchased: (eventId: string, purchased: boolean) =>
    request<{ id: string; purchased: boolean }>(
      `/api/shows/${encodeURIComponent(eventId)}/purchased`,
      { method: 'PUT', body: JSON.stringify({ purchased }) },
    ),
}
