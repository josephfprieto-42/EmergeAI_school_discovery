import { create } from 'zustand'
import { api } from './api'
import type { AppConfig, Category, ChatMessage, CompareResponse, Origin, Preferences, RecommendResponse, School } from './types'

export type PanelMode = 'explore' | 'match'

interface Filters {
  categories: Category[]
  grade: number | null
  flGrades: string[]
  q: string
  radius: number | null
}

interface State {
  config: AppConfig | null
  loadConfig: () => Promise<void>

  mode: PanelMode
  setMode: (m: PanelMode) => void

  filters: Filters
  setFilters: (f: Partial<Filters>) => void
  toggleCategory: (c: Category) => void
  toggleFlGrade: (g: string) => void

  origin: Origin | null
  setOrigin: (o: Origin | null) => void
  locate: (q: string) => Promise<void>
  locateError: string | null

  schools: School[]
  schoolsLoading: boolean
  loadSchools: () => Promise<void>

  selectedId: number | null
  selected: School | null
  select: (id: number | null) => Promise<void>
  hoverId: number | null
  setHover: (id: number | null) => void

  compareIds: number[]
  toggleCompare: (id: number) => void
  clearCompare: () => void
  compareOpen: boolean
  setCompareOpen: (v: boolean) => void
  compareResult: CompareResponse | null
  compareLoading: boolean
  runCompare: () => Promise<void>

  chat: ChatMessage[]
  chatLoading: boolean
  prefs: Preferences | null
  recommendation: RecommendResponse | null
  sendChat: (message: string) => Promise<void>
  resetChat: () => void

  fitRequest: number
  requestFit: () => void
}

let loadSeq = 0

export const useStore = create<State>((set, get) => ({
  config: null,
  loadConfig: async () => {
    const config = await api.config()
    set({ config })
  },

  mode: 'explore',
  setMode: (mode) => set({ mode }),

  filters: { categories: [], grade: null, flGrades: [], q: '', radius: null },
  setFilters: (f) => {
    set((s) => ({ filters: { ...s.filters, ...f } }))
    void get().loadSchools()
  },
  toggleCategory: (c) => {
    const cur = get().filters.categories
    get().setFilters({ categories: cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c] })
  },
  toggleFlGrade: (g) => {
    const cur = get().filters.flGrades
    get().setFilters({ flGrades: cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g] })
  },

  origin: null,
  locateError: null,
  setOrigin: (origin) => {
    set({ origin, locateError: null })
    void get().loadSchools()
    get().requestFit()
  },
  locate: async (q) => {
    try {
      const g = await api.geocode(q)
      get().setOrigin({ lat: g.lat, lng: g.lon, label: g.label })
    } catch (e) {
      set({ locateError: (e as Error).message })
    }
  },

  schools: [],
  schoolsLoading: false,
  loadSchools: async () => {
    const seq = ++loadSeq
    const { filters, origin } = get()
    set({ schoolsLoading: true })
    try {
      const r = await api.schools({
        categories: filters.categories,
        grade: filters.grade,
        flGrades: filters.flGrades,
        q: filters.q,
        lat: origin?.lat,
        lon: origin?.lng,
        radius: origin ? filters.radius : null,
      })
      if (seq === loadSeq) set({ schools: r.items, schoolsLoading: false })
    } catch {
      if (seq === loadSeq) set({ schoolsLoading: false })
    }
  },

  selectedId: null,
  selected: null,
  select: async (id) => {
    if (id == null) {
      set({ selectedId: null, selected: null })
      return
    }
    const cached = get().schools.find((s) => s.id === id) ?? get().recommendation?.results.find((s) => s.id === id) ?? null
    set({ selectedId: id, selected: cached })
    try {
      const full = await api.school(id, get().origin)
      if (get().selectedId === id) set({ selected: { ...cached, ...full, ranking: cached?.ranking } })
    } catch {
      /* keep cached */
    }
  },
  hoverId: null,
  setHover: (hoverId) => set({ hoverId }),

  compareIds: [],
  toggleCompare: (id) =>
    set((s) => {
      if (s.compareIds.includes(id)) return { compareIds: s.compareIds.filter((x) => x !== id), compareResult: null }
      if (s.compareIds.length >= 4) return {}
      return { compareIds: [...s.compareIds, id], compareResult: null }
    }),
  clearCompare: () => set({ compareIds: [], compareResult: null, compareOpen: false }),
  compareOpen: false,
  setCompareOpen: (compareOpen) => {
    set({ compareOpen })
    if (compareOpen && !get().compareResult) void get().runCompare()
  },
  compareResult: null,
  compareLoading: false,
  runCompare: async () => {
    const { compareIds, origin, prefs } = get()
    if (compareIds.length < 2) return
    set({ compareLoading: true })
    try {
      const r = await api.compare({ ids: compareIds, origin: origin ? [origin.lat, origin.lng] : null, preferences: prefs })
      set({ compareResult: r, compareLoading: false })
    } catch {
      set({ compareLoading: false })
    }
  },

  chat: [],
  chatLoading: false,
  prefs: null,
  recommendation: null,
  sendChat: async (message) => {
    const { chat, prefs, origin } = get()
    const history = chat
    set({ chat: [...chat, { role: 'user', content: message }], chatLoading: true })
    try {
      const r = await api.recommend({ message, history, preferences: prefs, origin: origin ? [origin.lat, origin.lng] : null, limit: 6 })
      const reply = r.follow_up ? `${r.summary}\n\n${r.follow_up}` : r.summary
      set((s) => ({ chat: [...s.chat, { role: 'assistant', content: reply }], chatLoading: false, prefs: r.preferences, recommendation: r }))
      if (r.origin && (!origin || Math.abs(origin.lat - r.origin[0]) > 1e-6 || Math.abs(origin.lng - r.origin[1]) > 1e-6)) {
        set({ origin: { lat: r.origin[0], lng: r.origin[1], label: r.origin_label ?? 'Your location' } })
      }
      // Mirror extracted preferences into the explore filters so the map reflects them.
      const f: Partial<Filters> = {}
      if (r.preferences.child_grade != null) f.grade = r.preferences.child_grade
      if (r.preferences.categories?.length) f.categories = r.preferences.categories
      if (r.preferences.radius_miles) f.radius = r.preferences.radius_miles
      set((s) => ({ filters: { ...s.filters, ...f } }))
      void get().loadSchools()
      get().requestFit()
    } catch (e) {
      set((s) => ({ chat: [...s.chat, { role: 'assistant', content: `Sorry, something went wrong: ${(e as Error).message}` }], chatLoading: false }))
    }
  },
  resetChat: () => set({ chat: [], prefs: null, recommendation: null }),

  fitRequest: 0,
  requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),
}))
