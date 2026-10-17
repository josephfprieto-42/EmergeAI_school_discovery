import type { AppConfig, ChatMessage, CompareResponse, Preferences, RecommendResponse, School } from './types'

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...init })
  if (!r.ok) {
    let detail = r.statusText
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return r.json() as Promise<T>
}

export const api = {
  config: () => http<AppConfig>('/api/config'),

  geocode: (q: string) => http<{ lat: number; lon: number; label: string; provider: string }>(`/api/geocode?q=${encodeURIComponent(q)}`),

  schools: (params: {
    categories?: string[]
    grade?: number | null
    flGrades?: string[]
    q?: string
    lat?: number
    lon?: number
    radius?: number | null
  }) => {
    const sp = new URLSearchParams()
    if (params.categories?.length) sp.set('category', params.categories.join(','))
    if (params.grade != null) sp.set('grade', String(params.grade))
    if (params.flGrades?.length) sp.set('fl_grade', params.flGrades.join(','))
    if (params.q) sp.set('q', params.q)
    if (params.lat != null && params.lon != null) {
      sp.set('lat', String(params.lat))
      sp.set('lon', String(params.lon))
      if (params.radius) sp.set('radius', String(params.radius))
    }
    return http<{ count: number; items: School[] }>(`/api/schools?${sp}`)
  },

  school: (id: number, origin?: { lat: number; lng: number } | null) => {
    const sp = new URLSearchParams()
    if (origin) {
      sp.set('lat', String(origin.lat))
      sp.set('lon', String(origin.lng))
    }
    return http<School>(`/api/schools/${id}?${sp}`)
  },

  recommend: (body: { message: string; history: ChatMessage[]; preferences?: Preferences | null; origin?: [number, number] | null; limit?: number }) =>
    http<RecommendResponse>('/api/recommend', { method: 'POST', body: JSON.stringify(body) }),

  compare: (body: { ids: number[]; origin?: [number, number] | null; preferences?: Preferences | null }) =>
    http<CompareResponse>('/api/compare', { method: 'POST', body: JSON.stringify(body) }),
}
