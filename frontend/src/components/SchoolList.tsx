import clsx from 'clsx'
import { ChevronLeft, ChevronRight, GitCompareArrows, MapPin } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { fmtMiles, gradeSpan, SUBTYPE_LABEL } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'
import { CategoryPill, Chip, EmptyState, GradeBadge, Spinner } from './ui'

const PAGE_SIZE = 20

function savedSchools(schools: School[], recommended: School[], selected: School | null, favoriteIds: number[]): School[] {
  const byId = new Map<number, School>()
  for (const school of schools) byId.set(school.id, school)
  for (const school of recommended) if (!byId.has(school.id)) byId.set(school.id, school)
  if (selected && !byId.has(selected.id)) byId.set(selected.id, selected)
  return favoriteIds.flatMap((id) => {
    const school = byId.get(id)
    return school ? [school] : []
  })
}

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
            {school.distance_miles != null && (
              <span className="shrink-0 text-right text-xs font-medium text-slate-500">
                {fmtMiles(school.distance_miles)}
                {school.detour_miles != null && (
                  <span className="block text-[10px] font-normal text-slate-400" title="Miles added to the home-to-work trip">
                    {school.detour_miles <= 0.5 ? 'on the way to work' : `+${school.detour_miles.toFixed(1)} mi detour`}
                  </span>
                )}
                {school.detour_miles == null && school.work_miles != null && (
                  <span className="block text-[10px] font-normal text-slate-400">{fmtMiles(school.work_miles)} from work</span>
                )}
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
            <CategoryPill category={school.category} />
            {school.cost === 'tuition-free' && <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">Tuition-free</span>}
            {school.cost === 'not reported' && <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">Price not reported</span>}
            {school.after_school_care && (
              <span className="rounded-full bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium text-sky-700" title={(school.after_school_care_names ?? []).join(', ')}>
                After-school care on campus
              </span>
            )}
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
          inCompare ? 'bg-brand-500 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200 md:opacity-0 md:group-hover:opacity-100',
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
  const { schools, schoolsLoading, origin, favoriteIds, recommendation, selected } = useStore()
  const [savedOnly, setSavedOnly] = useState(false)
  const [page, setPage] = useState(0)
  const [tracked, setTracked] = useState({ schools, savedOnly, favoriteIds })
  const listRef = useRef<HTMLDivElement>(null)
  const listed = savedOnly ? savedSchools(schools, recommendation?.results ?? [], selected, favoriteIds) : schools

  if (schools !== tracked.schools || savedOnly !== tracked.savedOnly || favoriteIds !== tracked.favoriteIds) {
    setTracked({ schools, savedOnly, favoriteIds })
    setPage(0)
  }

  const pageCount = Math.max(1, Math.ceil(listed.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const start = safePage * PAGE_SIZE
  const visible = listed.slice(start, start + PAGE_SIZE)
  const rangeEnd = start + visible.length

  useLayoutEffect(() => {
    if (listRef.current) listRef.current.scrollTop = 0
  }, [safePage])

  function goToPage(next: number) {
    setPage(next)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 text-xs text-slate-500">
        <span className="min-w-0">
          {schoolsLoading ? <Spinner className="size-3" /> : <strong className="text-slate-800">{listed.length.toLocaleString()}</strong>}{' '}
          {savedOnly ? 'saved' : 'providers'}
          {!savedOnly && (origin ? ` near ${origin.label}` : ' in Miami-Dade')}
          {visible.length > 0 && (
            <span className="text-slate-400">
              {' '}
              · {start + 1}–{rangeEnd}
            </span>
          )}
        </span>
        <Chip active={savedOnly} onClick={() => setSavedOnly((v) => !v)}>
          Saved{favoriteIds.length > 0 ? ` ${favoriteIds.length}` : ''}
        </Chip>
      </div>
      <div ref={listRef} className="scrollbar-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {!schoolsLoading && listed.length === 0 && (
          <EmptyState
            title={savedOnly ? 'No saved schools' : 'No matches'}
            body={savedOnly ? 'Save a school from its details to see it here.' : 'Try removing a filter or widening the distance.'}
          />
        )}
        {visible.map((s) => (
          <SchoolCard key={s.id} school={s} />
        ))}
      </div>
      {listed.length > PAGE_SIZE && (
        <div className="flex shrink-0 items-center justify-between gap-2 border-t border-slate-200 bg-white px-3 py-2">
          <button
            type="button"
            onClick={() => goToPage(safePage - 1)}
            disabled={safePage === 0}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-transparent"
          >
            <ChevronLeft className="size-3.5" />
            Previous
          </button>
          <span className="text-xs text-slate-500">
            Page {safePage + 1} of {pageCount}
          </span>
          <button
            type="button"
            onClick={() => goToPage(safePage + 1)}
            disabled={safePage >= pageCount - 1}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300 disabled:hover:bg-transparent"
          >
            Next
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}
