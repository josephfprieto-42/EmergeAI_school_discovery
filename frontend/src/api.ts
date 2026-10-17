import type { AppConfig, CompareResponse, HouseholdState, Preferences, RecommendResponse, School, SessionState } from './types'

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
  if (r.status === 204) return undefined as T
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
    program?: string | null
    religious?: boolean
    scholarship?: boolean
    assigned?: boolean
  }) => {
    const sp = new URLSearchParams()
    if (params.categories?.length) sp.set('category', params.categories.join(','))
    if (params.grade != null) sp.set('grade', String(params.grade))
    if (params.flGrades?.length) sp.set('fl_grade', params.flGrades.join(','))
    if (params.q) sp.set('q', params.q)
    if (params.program) sp.set('program', params.program)
    if (params.religious) sp.set('religious', 'true')
    if (params.scholarship) sp.set('scholarship', 'true')
    if (params.assigned) sp.set('assigned', 'true')
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

  recommend: (body: {
    message: string
    session_id?: string | null
    origin?: [number, number] | null
    origin_label?: string | null
    radius_miles?: number | null
    remember_location?: boolean
    household_id?: string | null
    limit?: number
  }) => http<RecommendResponse>('/api/recommend', { method: 'POST', body: JSON.stringify(body) }),

  session: (id: string) => http<SessionState>(`/api/sessions/${id}`),

  deleteSession: (id: string) => http<void>(`/api/sessions/${id}`, { method: 'DELETE' }),

  household: (id: string) => http<HouseholdState>(`/api/households/${id}`),

  deleteHousehold: (id: string) => http<void>(`/api/households/${id}`, { method: 'DELETE' }),

  clearSessionOrigin: (id: string) => http<void>(`/api/sessions/${id}/origin`, { method: 'DELETE' }),

  compare: (body: { ids: number[]; origin?: [number, number] | null; preferences?: Preferences | null }) =>
    http<CompareResponse>('/api/compare', { method: 'POST', body: JSON.stringify(body) }),
}
