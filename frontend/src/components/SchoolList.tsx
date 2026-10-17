import clsx from 'clsx'
import { GitCompareArrows, MapPin } from 'lucide-react'
import { useMemo } from 'react'
import { fmtMiles, gradeSpan, SUBTYPE_LABEL } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'
import { CategoryPill, EmptyState, GradeBadge, Spinner } from './ui'

export function SchoolCard({ school, rank, why }: { school: School; rank?: number; why?: string }) {
  const { selectedId, select, setHover, compareIds, toggleCompare } = useStore()
  const active = selectedId === school.id
  const inCompare = compareIds.includes(school.id)
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => void select(school.id)}
      onKeyDown={(e) => e.key === 'Enter' && void select(school.id)}
      onMouseEnter={() => setHover(school.id)}
      onMouseLeave={() => setHover(null)}
      className={clsx(
        'group relative cursor-pointer rounded-2xl border bg-white p-3 shadow-sm transition hover:shadow-md',
        active ? 'border-brand-500 ring-4 ring-brand-500/15' : 'border-slate-200 hover:border-slate-300',
      )}
    >
      <div className="flex items-start gap-3">
        {rank != null && (
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">{rank}</div>
        )}
        <GradeBadge grade={school.fl_grade} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900" title={school.name}>
              {school.name}
            </h3>
            {school.distance_miles != null && <span className="shrink-0 text-xs font-medium text-slate-500">{fmtMiles(school.distance_miles)}</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <CategoryPill category={school.category} />
            <span>{SUBTYPE_LABEL[school.subtype] ?? school.subtype}</span>
            <span>·</span>
            <span>Grades {gradeSpan(school.grade_low, school.grade_high, school.grades_text)}</span>
          </div>
          <div className="mt-1 flex items-center gap-1 truncate text-xs text-slate-400">
            <MapPin className="size-3 shrink-0" />
            <span className="truncate">
              {school.address}
              {school.city ? `, ${school.city}` : ''}
            </span>
          </div>
          {why && <p className="mt-2 text-xs leading-relaxed text-slate-600">{why}</p>}
        </div>
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          toggleCompare(school.id)
        }}
        className={clsx(
          'absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition',
          inCompare ? 'bg-brand-500 text-white' : 'bg-slate-100 text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-200',
        )}
        title={inCompare ? 'Remove from compare' : 'Add to compare'}
      >
        <GitCompareArrows className="size-3" />
        {inCompare ? 'Comparing' : 'Compare'}
      </button>
    </div>
  )
}

export function SchoolList() {
  const { schools, schoolsLoading, origin } = useStore()
  const visible = useMemo(() => schools.slice(0, 150), [schools])
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1 text-xs text-slate-500">
        <span>
          {schoolsLoading ? <Spinner className="size-3" /> : <strong className="text-slate-800">{schools.length.toLocaleString()}</strong>} providers
          {origin ? ` near ${origin.label}` : ' in Miami-Dade'}
        </span>
        {schools.length > visible.length && <span>Showing first {visible.length}</span>}
      </div>
      {!schoolsLoading && schools.length === 0 && <EmptyState title="No matches" body="Try removing a filter or widening the distance." />}
      {visible.map((s) => (
        <SchoolCard key={s.id} school={s} />
      ))}
    </div>
  )
}
