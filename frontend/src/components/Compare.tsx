import clsx from 'clsx'
import { GitCompareArrows, X } from 'lucide-react'
import { Fragment, type ReactNode } from 'react'
import { fmtNum, fmtPct, gradeSpan, SUBTYPE_LABEL } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'
import { CategoryPill, GradeBadge, Spinner } from './ui'

export function CompareTray() {
  const { compareIds, schools, recommendation, toggleCompare, clearCompare, setCompareOpen } = useStore()
  if (compareIds.length === 0) return null
  const pool = [...schools, ...(recommendation?.results ?? [])]
  const items = compareIds.map((id) => pool.find((s) => s.id === id)).filter((s): s is School => !!s)
  return (
    <div className="pointer-events-auto flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/95 p-2 pl-3 shadow-2xl backdrop-blur">
      <GitCompareArrows className="size-4 text-slate-500" />
      <div className="flex max-w-[60vw] items-center gap-1.5 overflow-x-auto">
        {items.map((s) => (
          <span key={s.id} className="inline-flex shrink-0 items-center gap-1 rounded-full bg-slate-100 py-1 pl-2 pr-1 text-xs font-medium text-slate-700">
            <GradeBadge grade={s.fl_grade} size="sm" />
            <span className="max-w-[140px] truncate">{s.name}</span>
            <button onClick={() => toggleCompare(s.id)} className="rounded-full p-0.5 hover:bg-slate-200" aria-label="Remove">
              <X className="size-3" />
            </button>
          </span>
        ))}
        {compareIds.length < 4 && <span className="shrink-0 text-xs text-slate-400">Add up to {4 - compareIds.length} more</span>}
      </div>
      <button onClick={() => setCompareOpen(true)} disabled={compareIds.length < 2} className="rounded-xl bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-40">
        Compare {compareIds.length >= 2 ? `(${compareIds.length})` : ''}
      </button>
      <button onClick={clearCompare} className="rounded-xl p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Clear">
        <X className="size-4" />
      </button>
    </div>
  )
}

type Row = { label: string; render: (s: School) => ReactNode; better?: (a: School) => number | null; group?: string }

const ROWS: Row[] = [
  { label: 'Type', render: (s) => <span className="text-xs">{SUBTYPE_LABEL[s.subtype] ?? s.subtype}</span> },
  { label: 'Grades served', render: (s) => gradeSpan(s.grade_low, s.grade_high, s.grades_text) },
  { label: 'Distance from home', render: (s) => (s.distance_miles != null ? `${s.distance_miles.toFixed(1)} mi` : '—'), better: (s) => (s.distance_miles != null ? -s.distance_miles : null) },
  { label: 'Enrollment', render: (s) => fmtNum(s.enrollment ?? s.capacity), group: 'Size & staffing' },
  { label: 'Student : teacher', render: (s) => (s.student_teacher_ratio != null ? `${Math.round(s.student_teacher_ratio)} : 1` : 'Not reported'), better: (s) => (s.student_teacher_ratio != null ? -s.student_teacher_ratio : null) },
  { label: 'Florida DOE grade', render: (s) => <GradeBadge grade={s.fl_grade} />, better: (s) => ({ A: 5, B: 4, C: 3, D: 2, F: 1 }[s.fl_grade ?? ''] ?? null), group: 'Academics (FLDOE 2025-26)' },
  { label: 'Prior years', render: (s) => (s.fl_grade_prev1 || s.fl_grade_prev2 ? `${s.fl_grade_prev1 ?? '—'} · ${s.fl_grade_prev2 ?? '—'}` : 'Not reported') },
  { label: 'ELA proficiency', render: (s) => fmtPct(s.ela_ach), better: (s) => s.ela_ach },
  { label: 'Math proficiency', render: (s) => fmtPct(s.math_ach), better: (s) => s.math_ach },
  { label: 'Science', render: (s) => fmtPct(s.sci_ach), better: (s) => s.sci_ach },
  { label: 'Learning gains (ELA / Math)', render: (s) => (s.ela_gains != null || s.math_gains != null ? `${fmtPct(s.ela_gains)} / ${fmtPct(s.math_gains)}` : '—') },
  { label: 'Graduation rate', render: (s) => fmtPct(s.grad_rate), better: (s) => s.grad_rate },
  { label: 'Points earned', render: (s) => fmtPct(s.pct_points), better: (s) => s.pct_points },
  { label: 'Econ. disadvantaged', render: (s) => fmtPct(s.pct_econ_disadvantaged), group: 'Community' },
  { label: 'Free/reduced lunch', render: (s) => fmtPct(s.frl_pct) },
  { label: 'Title I', render: (s) => (s.fl_title_i == null ? '—' : s.fl_title_i ? 'Yes' : 'No') },
  { label: 'Magnet', render: (s) => (s.magnet == null ? '—' : s.magnet ? 'Yes' : 'No') },
  { label: 'Programs (name signals)', render: (s) => (s.ranking?.keyword_hits?.length ? s.ranking.keyword_hits.map((h) => h.split(':').pop()).join(', ') : '—'), group: 'Fit' },
  { label: 'Match score', render: (s) => (s.ranking ? `${Math.round(s.ranking.score * 100)} / 100` : '—'), better: (s) => s.ranking?.score ?? null },
]

export function CompareModal() {
  const { compareOpen, setCompareOpen, compareResult, compareLoading, toggleCompare, select, recommendation } = useStore()
  if (!compareOpen) return null
  const base = compareResult?.schools ?? []
  const schools = base.map((s) => ({ ...s, ranking: recommendation?.results.find((r) => r.id === s.id)?.ranking }))
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 backdrop-blur-sm sm:items-center sm:p-6" onClick={() => setCompareOpen(false)}>
      <div className="flex max-h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Side-by-side comparison</h2>
            <p className="text-xs text-slate-500">Verified public data · Miami-Dade County GIS, Florida DOE, NCES</p>
          </div>
          <button onClick={() => setCompareOpen(false)} className="rounded-xl p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        <div className="scrollbar-thin flex-1 overflow-auto">
          {compareLoading || !compareResult ? (
            <div className="flex items-center justify-center gap-2 p-16 text-sm text-slate-500">
              <Spinner /> Comparing…
            </div>
          ) : (
            <>
              <div className="border-b border-slate-100 bg-slate-50 px-5 py-4">
                <p className="text-sm leading-relaxed text-slate-700">{compareResult.summary}</p>
                {compareResult.tradeoffs.length > 0 && (
                  <ul className="mt-3 grid gap-1.5 text-xs text-slate-600 sm:grid-cols-2">
                    {compareResult.tradeoffs.map((t, i) => (
                      <li key={i} className="flex gap-2 rounded-lg bg-white px-3 py-2 ring-1 ring-slate-100">
                        <span className="mt-1 size-1.5 shrink-0 rounded-full bg-brand-500" />
                        {t}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-2 text-[11px] text-slate-400">{compareResult.llm_used ? 'Narrative generated by AI using only the fields shown below.' : 'Narrative generated from stored data (no OpenAI key configured).'}</div>
              </div>

              <table className="w-full border-separate border-spacing-0 text-sm">
                <thead className="sticky top-0 z-10 bg-white">
                  <tr>
                    <th className="w-44 border-b border-slate-200 px-5 py-3 text-left text-xs font-medium text-slate-400"></th>
                    {schools.map((s) => (
                      <th key={s.id} className="min-w-[180px] border-b border-slate-200 px-3 py-3 text-left align-top">
                        <button onClick={() => void select(s.id)} className="text-left font-semibold leading-tight text-slate-900 hover:text-brand-600">
                          {s.name}
                        </button>
                        <div className="mt-1 flex items-center gap-2">
                          <CategoryPill category={s.category} />
                          <button onClick={() => toggleCompare(s.id)} className="text-[11px] text-slate-400 hover:text-rose-600">
                            remove
                          </button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map((row) => {
                    const vals = row.better ? schools.map((s) => row.better!(s)) : []
                    const max = vals.filter((v): v is number => v != null).reduce((a, b) => Math.max(a, b), -Infinity)
                    const distinct = new Set(vals.filter((v) => v != null)).size > 1
                    return (
                      <Fragment key={row.label}>
                        {row.group && (
                          <tr>
                            <td colSpan={schools.length + 1} className="bg-slate-50 px-5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                              {row.group}
                            </td>
                          </tr>
                        )}
                        <tr className="hover:bg-slate-50/60">
                          <td className="border-b border-slate-100 px-5 py-2.5 text-xs font-medium text-slate-500">{row.label}</td>
                          {schools.map((s, i) => (
                            <td key={s.id} className={clsx('border-b border-slate-100 px-3 py-2.5 font-medium text-slate-800', row.better && distinct && vals[i] === max && 'bg-emerald-50 text-emerald-800')}>
                              {row.render(s)}
                            </td>
                          ))}
                        </tr>
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
