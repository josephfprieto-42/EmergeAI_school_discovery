import type { Category } from '../types'

export const CATEGORY_META: Record<Category, { label: string; short: string; color: string; bg: string; text: string; ring: string }> = {
  public: { label: 'Public', short: 'Public', color: '#001ae6', bg: 'bg-brand-50', text: 'text-brand-700', ring: 'ring-brand-200' },
  charter: { label: 'Charter', short: 'Charter', color: '#7c3aed', bg: 'bg-violet-50', text: 'text-violet-700', ring: 'ring-violet-200' },
  private: { label: 'Private', short: 'Private', color: '#d97706', bg: 'bg-amber-50', text: 'text-amber-700', ring: 'ring-amber-200' },
  early_childhood: { label: 'Early childhood', short: 'Early', color: '#059669', bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-200' },
}

export const SUBTYPE_LABEL: Record<string, string> = {
  traditional: 'District school',
  charter: 'Charter school',
  private: 'Private school',
  daycare: 'Licensed child care',
  head_start: 'Head Start',
  early_head_start: 'Early Head Start',
  alternative: 'Alternative school',
  special_center: 'Special education center',
  primary_learning_center: 'Primary learning center',
  virtual: 'Virtual school',
}

export const GRADE_OPTIONS: { value: number; label: string }[] = [
  { value: -2, label: 'Infant / toddler (0-2)' },
  { value: -1, label: 'Pre-K (3-4)' },
  { value: 0, label: 'Kindergarten' },
  ...Array.from({ length: 12 }, (_, i) => ({ value: i + 1, label: `Grade ${i + 1}` })),
]

export function gradeLabel(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n === -2) return 'Infant'
  if (n === -1) return 'PK'
  if (n === 0) return 'K'
  return String(n)
}

export function gradeSpan(low: number | null, high: number | null, text: string | null): string {
  if (low != null && high != null) return low === high ? gradeLabel(low) : `${gradeLabel(low)}–${gradeLabel(high)}`
  return text ?? 'Not reported'
}

export const FL_GRADE_STYLE: Record<string, string> = {
  A: 'bg-emerald-500 text-white',
  B: 'bg-lime-500 text-white',
  C: 'bg-amber-400 text-slate-900',
  D: 'bg-orange-500 text-white',
  F: 'bg-rose-600 text-white',
  I: 'bg-slate-300 text-slate-700',
}

export function fmtNum(n: number | null | undefined, suffix = ''): string {
  if (n == null) return 'Not reported'
  return `${n.toLocaleString()}${suffix}`
}

export function fmtPct(n: number | null | undefined): string {
  return n == null ? '—' : `${Math.round(n)}%`
}

export function fmtMiles(n: number | null | undefined): string {
  return n == null ? '' : `${n.toFixed(1)} mi`
}

export const PRIORITY_LABEL: Record<string, string> = {
  academics: 'Strong academics',
  distance: 'Close to home',
  small_school: 'Small school',
  large_school: 'Large school',
  diversity: 'Diversity',
  stem: 'STEM',
  arts: 'Arts',
  language: 'Language / bilingual',
  magnet: 'Magnet programs',
  religious: 'Faith-based',
  montessori: 'Montessori',
  special_needs: 'Special needs support',
  gifted: 'Gifted / advanced',
  affordability: 'Affordability',
  early_childhood: 'Early childhood',
}
