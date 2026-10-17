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
  ranking?: {
    score: number
    components: Record<string, number>
    reasons: string[]
    keyword_hits: string[]
  }
}

export interface Preferences {
  location_text?: string | null
  child_grade?: number | null
  child_grades?: number[]
  categories?: Category[]
  radius_miles?: number | null
  priorities?: string[]
  keywords?: string[]
  min_fl_grade?: 'A' | 'B' | 'C' | null
  notes?: string | null
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

export interface RecommendResponse {
  preferences: Preferences
  origin: [number, number] | null
  origin_label: string | null
  summary: string
  follow_up: string | null
  results: School[]
  explanations: Explanation[]
  candidates_considered: number
  llm_used: boolean
}

export interface CompareResponse {
  schools: School[]
  summary: string
  tradeoffs: string[]
  llm_used: boolean
}

export interface AppConfig {
  maps_browser_key: string | null
  map_id: string | null
  center: { lat: number; lng: number }
  features: { llm: boolean; google_geocoding: boolean; google_maps: boolean }
}

export interface Origin {
  lat: number
  lng: number
  label: string
}
