export type Category = 'public' | 'charter' | 'private' | 'early_childhood'

export interface School {
  id: number
  source: string
  mdcps_id: string | null
  name: string
  category: Category
  subtype: string
  address: string | null
  city: string | null
  zip: string | null
  phone: string | null
  website: string | null
  lat: number
  lon: number
  grade_low: number | null
  grade_high: number | null
  grade_low_label: string | null
  grade_high_label: string | null
  grades_text: string | null
  enrollment: number | null
  capacity: number | null
  year_established: number | null
  coed: string | null
  license_number: string | null
  license_expires: string | null
  status: string | null
  region: string | null
  fl_grade: string | null
  fl_grade_prev1: string | null
  fl_grade_prev2: string | null
  grade_history: Record<string, string> | null
  ela_ach: number | null
  ela_gains: number | null
  math_ach: number | null
  math_gains: number | null
  sci_ach: number | null
  ss_ach: number | null
  grad_rate: number | null
  college_career_accel: number | null
  pct_points: number | null
  pct_econ_disadvantaged: number | null
  fl_title_i: boolean | null
  fl_school_type: string | null
  frl_pct: number | null
  teachers_fte: number | null
  student_teacher_ratio: number | null
  magnet: boolean | null
  title_i_schoolwide: boolean | null
  nces_enrollment: number | null
  distance_miles: number | null
  serves_grades?: number[]
  cost?: 'tuition-free' | 'not reported'
  after_school_care?: boolean
  after_school_care_names?: string[]
  work_miles?: number | null
  detour_miles?: number | null
  activity_miles?: number | null
  activity_detours?: { label: string; miles: number; detour_miles?: number }[]
  programs?: SchoolProgram[]
  academics?: SchoolAcademics | null
  sports?: SchoolSport[]
  verified_programs?: { type: string; name: string; themes?: string[]; eligibility?: string | null }[]
  attendance_levels?: string[]
  assigned_zones?: { level: string; grade_low: number | null; grade_high: number | null; name?: string }[]
  religious?: boolean | null
  denomination?: string | null
  nonprofit?: boolean | null
  accreditation?: string | null
  scholarship_programs?: string[]
  directory_survey_year?: number | null
  directory_outdated?: boolean | null
  ranking?: {
    score: number
    components: Record<string, number>
    reasons: string[]
    keyword_hits: string[]
  }
}

export interface SchoolProgram {
  name: string
  kind: 'magnet' | 'choice'
  themes?: string[]
  eligibility?: string | null
  admission_note?: string | null
  test_required?: boolean
  audition_required?: boolean
}

export interface SchoolAcademics {
  year: number
  ap_enrollment: number | null
  ap_math: number | null
  ap_science: number | null
  ap_compsci: number | null
  ap_language: number | null
  ap_other: number | null
  ib_enrollment: number | null
  gifted_enrollment: number | null
}

export interface SchoolSport {
  sport: string
  team: string | null
}

export interface Child {
  grade: number
  label?: string | null
}

export interface Preferences {
  location_text?: string | null
  child_grade?: number | null
  child_grades?: number[]
  children?: Child[]
  categories?: Category[]
  radius_miles?: number | null
  priorities?: string[]
  keywords?: string[]
  min_fl_grade?: 'A' | 'B' | 'C' | null
  notes?: string | null
  prefer_near?: 'home' | 'work' | 'route' | null
}

export interface ActivityPlace {
  label: string
  location_text?: string | null
  child_label?: string | null
}

export type ActivityInterest = 'arts' | 'stem' | 'language' | 'sports'

export interface Household {
  work_location_text?: string | null
  work_schedule_text?: string | null
  needs_after_school_care?: boolean | null
  activities?: ActivityPlace[]
  activity_interests?: ActivityInterest[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface Explanation {
  school_id: number
  why: string
  tradeoffs: string
}

export interface ChildGroup {
  grade: number
  label: string | null
  results: School[]
  candidates_considered: number
}

export interface RecommendResponse {
  session_id: string
  household_id?: string | null
  household?: Household | null
  preferences: Preferences
  origin: [number, number] | null
  origin_label: string | null
  work?: [number, number] | null
  work_label?: string | null
  activity_points?: { label: string; lat: number; lon: number }[]
  summary: string
  follow_up: string | null
  /** discovering: nothing to rank on yet; preliminary: one anchor known; refined: grade and place known. */
  stage?: Stage
  /** Short acknowledgements of what this turn changed ("Switched to charter only"). */
  changes?: string[]
  question?: Question | null
  results: School[]
  groups?: ChildGroup[] | null
  explanations: Explanation[]
  candidates_considered: number
  llm_used: boolean
}

export type Stage = 'discovering' | 'preliminary' | 'refined'
export type Topic = 'children' | 'location' | 'categories' | 'priorities' | 'radius' | 'work' | 'min_fl_grade'

export interface QuestionOption {
  label: string
  /** Sent as the parent's message when tapped. */
  message: string
}

export interface Question {
  topic: Topic
  text: string
  options: QuestionOption[]
}

export interface SessionState {
  session_id: string
  messages: ChatMessage[]
  preferences: Preferences
  origin: [number, number] | null
  origin_label: string | null
  recommendation: RecommendResponse | null
  household_id?: string | null
  household?: Household | null
  asked?: Topic[]
}

export interface HouseholdState {
  household_id: string
  household: Household
  work: [number, number] | null
  work_label: string | null
}

export interface LatLngBounds {
  south: number
  west: number
  north: number
  east: number
}

export interface AppConfig {
  maps_browser_key: string | null
  map_id: string | null
  center: { lat: number; lng: number }
  /** County box used to accept a home address. */
  bounds: LatLngBounds
  /** School coordinates plus a buffer. The map cannot pan outside this box. */
  map_bounds: LatLngBounds
  features: { llm: boolean; google_geocoding: boolean; google_maps: boolean }
}

export interface Origin {
  lat: number
  lng: number
  label: string
}
