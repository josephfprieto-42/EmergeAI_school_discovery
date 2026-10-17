import { create } from 'zustand'
import { api } from './api'
import type { AppConfig, Category, ChatMessage, Household, Origin, Preferences, RecommendResponse, School } from './types'

const SESSION_KEY = 'schoolmatch.sessionId'
const HOUSEHOLD_KEY = 'schoolmatch.householdId'
const DEFAULT_RADIUS_MILES = 5
const OUTSIDE_COUNTY = 'Could not locate that place in Miami-Dade County'

function outsideCounty(lat: number, lng: number, config: AppConfig | null): boolean {
  const b = config?.bounds
  if (!b) return false
  return lat < b.south || lat > b.north || lng < b.west || lng > b.east
}

function samePoint(origin: Origin, lat: number, lng: number): boolean {
  return Math.abs(origin.lat - lat) < 1e-5 && Math.abs(origin.lng - lng) < 1e-5
}

export type PanelMode = 'explore' | 'match'

interface Filters {
  categories: Category[]
  grade: number | null
  flGrades: string[]
  q: string
  radius: number | null
  program: string | null
  religious: boolean
  scholarship: boolean
  assigned: boolean
}

const EMPTY_FILTERS: Filters = {
  categories: [],
  grade: null,
  flGrades: [],
  q: '',
  radius: null,
  program: null,
  religious: false,
  scholarship: false,
  assigned: false,
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
  clearFilters: () => void

  origin: Origin | null
  setOrigin: (o: Origin | null) => void
  locate: (q: string) => Promise<void>
  locateError: string | null
  setLocateError: (message: string | null) => void
  rememberLocation: boolean
  setRememberLocation: (remember: boolean) => Promise<void>

  schools: School[]
  schoolsLoading: boolean
  loadSchools: () => Promise<void>

  selectedId: number | null
  selected: School | null
  select: (id: number | null) => Promise<void>
  hoverId: number | null
  setHover: (id: number | null) => void

  chat: ChatMessage[]
  chatLoading: boolean
  chatHydrated: boolean
  sessionId: string | null
  prefs: Preferences | null
  recommendation: RecommendResponse | null
  /** Facts about the family that outlive one chat: work, schedule, activities. */
  householdId: string | null
  household: Household | null
  work: Origin | null
  forgetHousehold: () => Promise<void>
  sendChat: (message: string, options?: { preserveFilters?: boolean }) => Promise<void>
  restoreSession: () => Promise<void>
  resetChat: () => Promise<void>

  fitRequest: number
  requestFit: () => void
  /** Bumped to put the map back on its initial county view. */
  viewReset: number

  /** Height in px of UI covering the bottom of the map (mobile bottom sheet). 0 on desktop. */
  mapInsetBottom: number
  setMapInsetBottom: (px: number) => void
}

function applyChatFilters(set: (partial: (s: State) => Partial<State>) => void, prefs: Preferences, prev: Preferences | null) {
  const grades = prefs.children?.map((c) => c.grade) ?? prefs.child_grades ?? []
  const prevGrades = prev?.children?.map((c) => c.grade) ?? prev?.child_grades ?? []
  const f: Partial<Filters> = {}
  if (grades.length === 1) f.grade = grades[0]
  else if (grades.length > 1) f.grade = null
  else if (prevGrades.length > 0 || prev?.child_grade != null) f.grade = null
  if (prefs.categories?.length) f.categories = prefs.categories
  else if (prev?.categories?.length) f.categories = []
  if (prefs.radius_miles) f.radius = prefs.radius_miles
  else if (prev?.radius_miles) f.radius = null
  set((s) => ({ filters: { ...s.filters, ...f } }))
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

  filters: { ...EMPTY_FILTERS },
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
  clearFilters: () => {
    set((s) => ({
      filters: { ...EMPTY_FILTERS },
      selectedId: null,
      selected: null,
      hoverId: null,
      viewReset: s.viewReset + 1,
    }))
    void get().loadSchools()
  },

  origin: null,
  locateError: null,
  setLocateError: (locateError) => set({ locateError }),
  rememberLocation: false,
  setRememberLocation: async (rememberLocation) => {
    set({ rememberLocation })
    if (rememberLocation) return
    const id = get().sessionId
    if (!id) return
    try {
      await api.clearSessionOrigin(id)
    } catch {
      /* the session may not exist yet */
    }
  },
  setOrigin: (origin) => {
    if (!origin && !get().origin) return
    if (origin && outsideCounty(origin.lat, origin.lng, get().config)) {
      set({ locateError: OUTSIDE_COUNTY })
      return
    }
    const sessionId = origin ? null : get().sessionId
    set((s) => ({
      origin,
      locateError: null,
      rememberLocation: origin ? s.rememberLocation : false,
      filters: {
        ...s.filters,
        radius: origin ? (s.filters.radius ?? DEFAULT_RADIUS_MILES) : null,
      },
    }))
    if (sessionId) {
      void api.clearSessionOrigin(sessionId).catch(() => {
        /* the session may not exist yet */
      })
    }
    void get().loadSchools()
    get().requestFit()
  },
  locate: async (q) => {
    set({ locateError: null })
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
        program: filters.program,
        religious: filters.religious,
        scholarship: filters.scholarship,
        assigned: origin ? filters.assigned : false,
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

  chat: [],
  chatLoading: false,
  chatHydrated: false,
  sessionId: localStorage.getItem(SESSION_KEY),
  prefs: null,
  recommendation: null,
  householdId: localStorage.getItem(HOUSEHOLD_KEY),
  household: null,
  work: null,
  forgetHousehold: async () => {
    const id = get().householdId
    if (id) {
      try {
        await api.deleteHousehold(id)
      } catch {
        /* already gone */
      }
    }
    localStorage.removeItem(HOUSEHOLD_KEY)
    set({ householdId: null, household: null, work: null })
  },
  restoreSession: async () => {
    const id = localStorage.getItem(SESSION_KEY)
    const householdId = localStorage.getItem(HOUSEHOLD_KEY)
    if (householdId) {
      try {
        const h = await api.household(householdId)
        set({
          householdId: h.household_id,
          household: h.household,
          work: h.work ? { lat: h.work[0], lng: h.work[1], label: h.work_label ?? h.household.work_location_text ?? 'Work' } : null,
        })
      } catch {
        localStorage.removeItem(HOUSEHOLD_KEY)
        set({ householdId: null, household: null, work: null })
      }
    }
    if (!id) {
      set({ sessionId: null, chatHydrated: true })
      return
    }
    try {
      const s = await api.session(id)
      const origin = s.origin ? { lat: s.origin[0], lng: s.origin[1], label: s.origin_label ?? 'Your location' } : get().origin
      set({
        sessionId: s.session_id,
        chat: s.messages,
        prefs: s.preferences,
        recommendation: s.recommendation,
        origin,
        rememberLocation: Boolean(s.origin),
        chatHydrated: true,
      })
      if (s.household_id) {
        localStorage.setItem(HOUSEHOLD_KEY, s.household_id)
        set({ householdId: s.household_id, household: s.household ?? get().household })
      }
      applyChatFilters(set, s.preferences, null)
      if (origin && get().filters.radius == null) {
        set((state) => ({ filters: { ...state.filters, radius: DEFAULT_RADIUS_MILES } }))
      }
      if (s.recommendation || origin) get().requestFit()
      void get().loadSchools()
    } catch {
      localStorage.removeItem(SESSION_KEY)
      set({ sessionId: null, chat: [], prefs: null, recommendation: null, chatHydrated: true })
    }
  },
  sendChat: async (message, options) => {
    const { chat, origin, sessionId, filters, rememberLocation, householdId } = get()
    set({ chat: [...chat, { role: 'user', content: message }], chatLoading: true })
    try {
      const r = await api.recommend({
        message,
        session_id: sessionId,
        origin: origin ? [origin.lat, origin.lng] : null,
        origin_label: origin?.label ?? null,
        radius_miles: filters.radius,
        remember_location: rememberLocation,
        household_id: householdId,
        limit: 5,
      })
      localStorage.setItem(SESSION_KEY, r.session_id)
      if (r.household_id) localStorage.setItem(HOUSEHOLD_KEY, r.household_id)
      const work = r.work ? { lat: r.work[0], lng: r.work[1], label: r.work_label ?? r.household?.work_location_text ?? 'Work' } : null
      set({ householdId: r.household_id ?? householdId, household: r.household ?? null, work })
      const reply = r.follow_up ? `${r.summary}\n\n${r.follow_up}` : r.summary
      const prevPrefs = get().prefs
      const nextOrigin = r.origin
        ? {
            lat: r.origin[0],
            lng: r.origin[1],
            label: origin && samePoint(origin, r.origin[0], r.origin[1]) ? origin.label : (r.origin_label ?? 'Your location'),
          }
        : null
      const introducedOrigin = !origin && Boolean(nextOrigin)
      set((s) => ({
        chat: [...s.chat, { role: 'assistant', content: reply }],
        chatLoading: false,
        sessionId: r.session_id,
        prefs: r.preferences,
        recommendation: r,
        origin: nextOrigin,
      }))
      if (!options?.preserveFilters) {
        applyChatFilters(set, r.preferences, prevPrefs)
        if (introducedOrigin && !r.preferences.radius_miles && get().filters.radius == null) {
          set((s) => ({ filters: { ...s.filters, radius: DEFAULT_RADIUS_MILES } }))
        }
      }
      void get().loadSchools()
      get().requestFit()
    } catch (e) {
      set((s) => ({ chat: [...s.chat, { role: 'assistant', content: `Sorry, something went wrong: ${(e as Error).message}` }], chatLoading: false }))
    }
  },
  resetChat: async () => {
    const id = get().sessionId
    if (id) {
      try {
        await api.deleteSession(id)
      } catch {
        /* the next message starts a new session either way */
      }
    }
    localStorage.removeItem(SESSION_KEY)
    set((s) => ({
      sessionId: null,
      chat: [],
      prefs: null,
      recommendation: null,
      filters: { ...EMPTY_FILTERS },
      selectedId: null,
      selected: null,
      hoverId: null,
      viewReset: s.viewReset + 1,
    }))
    void get().loadSchools()
  },

  fitRequest: 0,
  requestFit: () => set((s) => ({ fitRequest: s.fitRequest + 1 })),
  viewReset: 0,

  mapInsetBottom: 0,
  setMapInsetBottom: (px) => {
    if (get().mapInsetBottom !== px) set({ mapInsetBottom: px })
  },
}))
