import clsx from 'clsx'
import { ChevronDown, Search } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { CATEGORY_META, GRADE_OPTIONS } from '../lib/format'
import { useStore } from '../store'
import type { Category } from '../types'
import { Chip } from './ui'

const CATS: Category[] = ['public', 'charter', 'private', 'early_childhood']
const RADII = [1, 2, 3, 5, 10]
const PROGRAMS: { id: string; label: string }[] = [
  { id: 'stem', label: 'STEM' },
  { id: 'arts', label: 'Arts' },
  { id: 'language', label: 'Language' },
  { id: 'gifted', label: 'Gifted' },
  { id: 'magnet', label: 'Magnet' },
  { id: 'choice', label: 'Choice' },
]

function FilterSection({
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  title: string
  summary: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div>
      <button type="button" aria-expanded={open} onClick={onToggle} className="flex w-full items-center gap-1.5 text-left">
        <ChevronDown className={clsx('size-3.5 shrink-0 text-slate-400 transition', !open && '-rotate-90')} />
        <span className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{title}</span>
        {!open && <span className="ml-auto truncate pl-2 text-[11px] font-normal normal-case tracking-normal text-slate-500">{summary}</span>}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  )
}

export function FilterBar() {
  const { filters, setFilters, toggleCategory, toggleFlGrade, origin } = useStore()
  const [q, setQ] = useState(filters.q)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [typeOpen, setTypeOpen] = useState(true)
  const [gradeOpen, setGradeOpen] = useState(true)
  const [flOpen, setFlOpen] = useState(false)
  const [factsOpen, setFactsOpen] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      if (q !== filters.q) setFilters({ q })
    }, 300)
    return () => clearTimeout(t)
  }, [q, filters.q, setFilters])

  const typeSummary = filters.categories.length
    ? CATS.filter((c) => filters.categories.includes(c))
        .map((c) => CATEGORY_META[c].label)
        .join(', ')
    : 'All types'
  const gradeSummary = filters.grade == null ? 'Any grade' : (GRADE_OPTIONS.find((g) => g.value === filters.grade)?.label ?? 'Any grade')
  const distanceSummary = filters.radius != null ? `Within ${filters.radius} mi` : origin ? 'Any distance' : 'Set a location first'
  const flSummary = filters.flGrades.length ? [...filters.flGrades].sort().join(', ') : 'Any grade'
  const factBits = [
    filters.program ? PROGRAMS.find((p) => p.id === filters.program)?.label : null,
    filters.religious ? 'Religious' : null,
    filters.scholarship ? 'Scholarship' : null,
    filters.assigned ? 'Assigned school' : null,
  ].filter(Boolean)
  const factsSummary = factBits.length ? factBits.join(', ') : 'Any'
  const filtersSummary = [
    typeSummary,
    filters.grade != null ? gradeSummary : null,
    filters.radius != null ? distanceSummary : null,
    factBits.length ? factsSummary : null,
    filters.flGrades.length ? flSummary : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search school names"
            className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-base shadow-sm outline-none ring-accent/40 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 md:text-sm"
          />
        </div>
        <button
          type="button"
          aria-expanded={filtersOpen}
          aria-label={`Filters: ${filtersSummary}`}
          onClick={() => setFiltersOpen((open) => !open)}
          className="flex max-w-[46%] shrink-0 items-center gap-1 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-left text-xs font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <span className="min-w-0 truncate font-normal text-slate-500">{filtersSummary}</span>
          <ChevronDown className={clsx('size-3.5 shrink-0 text-slate-400 transition', !filtersOpen && '-rotate-90')} />
        </button>
      </div>

      {filtersOpen && (
        <>
      <FilterSection title="School type" summary={typeSummary} open={typeOpen} onToggle={() => setTypeOpen((v) => !v)}>
        <div className="flex flex-wrap gap-1.5">
          {CATS.map((c) => (
            <Chip key={c} active={filters.categories.includes(c)} onClick={() => toggleCategory(c)} color={CATEGORY_META[c].color}>
              {CATEGORY_META[c].label}
            </Chip>
          ))}
        </div>
      </FilterSection>

      <FilterSection title="Grade and distance" summary={`${gradeSummary} · ${distanceSummary}`} open={gradeOpen} onToggle={() => setGradeOpen((v) => !v)}>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-400">Child's grade</span>
            <select
              value={filters.grade ?? ''}
              onChange={(e) => setFilters({ grade: e.target.value === '' ? null : Number(e.target.value) })}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-base shadow-sm outline-none focus:border-brand-500 md:text-sm"
            >
              <option value="">Any grade</option>
              {GRADE_OPTIONS.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-400">Distance</span>
            <select
              value={filters.radius ?? ''}
              disabled={!origin}
              onChange={(e) => {
                if (!useStore.getState().origin) return
                const radius = e.target.value === '' ? null : Number(e.target.value)
                if (radius === useStore.getState().filters.radius) return
                setFilters({ radius })
              }}
              className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-base shadow-sm outline-none focus:border-brand-500 disabled:bg-slate-50 disabled:text-slate-400 md:text-sm"
            >
              <option value="">{origin ? 'Any distance' : 'Set a location first'}</option>
              {RADII.map((r) => (
                <option key={r} value={r}>
                  Within {r} mi
                </option>
              ))}
            </select>
          </label>
        </div>
      </FilterSection>

      <FilterSection title="Verified programs and directory" summary={factsSummary} open={factsOpen} onToggle={() => setFactsOpen((v) => !v)}>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            {PROGRAMS.map((program) => (
              <Chip key={program.id} active={filters.program === program.id} onClick={() => setFilters({ program: filters.program === program.id ? null : program.id })}>
                {program.label}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Chip active={filters.religious} onClick={() => setFilters({ religious: !filters.religious })}>
              School-reported religious
            </Chip>
            <Chip active={filters.scholarship} onClick={() => setFilters({ scholarship: !filters.scholarship })}>
              Scholarship participant
            </Chip>
            <Chip active={filters.assigned} onClick={() => origin && setFilters({ assigned: !filters.assigned })}>
              Assigned school
            </Chip>
          </div>
          <p className="text-[11px] leading-snug text-slate-400">
            Programs come from the district catalog. Religious affiliation and scholarships are school-reported on the Florida private-school survey, not a tuition price. Assigned school needs a location.
          </p>
        </div>
      </FilterSection>

      <FilterSection title="Florida DOE grade" summary={flSummary} open={flOpen} onToggle={() => setFlOpen((v) => !v)}>
        <div className="flex gap-1.5">
          {['A', 'B', 'C', 'D', 'F'].map((g) => (
            <Chip key={g} active={filters.flGrades.includes(g)} onClick={() => toggleFlGrade(g)}>
              {g}
            </Chip>
          ))}
        </div>
      </FilterSection>
        </>
      )}
    </div>
  )
}
