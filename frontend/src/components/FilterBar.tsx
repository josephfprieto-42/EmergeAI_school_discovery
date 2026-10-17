import clsx from 'clsx'
import { ChevronDown, Search } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { CATEGORY_META, GRADE_OPTIONS } from '../lib/format'
import { useStore } from '../store'
import type { Category } from '../types'
import { Chip } from './ui'

const CATS: Category[] = ['public', 'charter', 'private', 'early_childhood']
const RADII = [1, 2, 3, 5, 10]

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
  const [typeOpen, setTypeOpen] = useState(true)
  const [gradeOpen, setGradeOpen] = useState(true)
  const [flOpen, setFlOpen] = useState(false)

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

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search school names (e.g. Montessori, Somerset, Coral)"
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-base shadow-sm outline-none ring-accent/40 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 md:text-sm"
        />
      </div>

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

      <FilterSection title="Florida DOE grade" summary={flSummary} open={flOpen} onToggle={() => setFlOpen((v) => !v)}>
        <div className="flex gap-1.5">
          {['A', 'B', 'C', 'D', 'F'].map((g) => (
            <Chip key={g} active={filters.flGrades.includes(g)} onClick={() => toggleFlGrade(g)}>
              {g}
            </Chip>
          ))}
        </div>
      </FilterSection>
    </div>
  )
}
