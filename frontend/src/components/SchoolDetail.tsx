import clsx from 'clsx'
import { ExternalLink, GitCompareArrows, Phone, X } from 'lucide-react'
import { fmtNum, fmtPct, gradeSpan, SUBTYPE_LABEL } from '../lib/format'
import { useStore } from '../store'
import { CategoryPill, GradeBadge, Stat } from './ui'

export function SchoolDetail() {
  const { selected, select, compareIds, toggleCompare, recommendation } = useStore()
  if (!selected) return null
  const s = selected
  const inCompare = compareIds.includes(s.id)
  const graded = s.category === 'public' || s.category === 'charter'
  const explanation = recommendation?.explanations.find((e) => e.school_id === s.id)
  const history = s.grade_history ? Object.entries(s.grade_history).sort((a, b) => Number(b[0]) - Number(a[0])).slice(0, 6) : []

  return (
    <aside className="pointer-events-auto flex h-full w-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
      <div className="flex items-start gap-3 border-b border-slate-100 p-4">
        <GradeBadge grade={s.fl_grade} size="lg" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-tight text-slate-900">{s.name}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <CategoryPill category={s.category} />
            <span>{SUBTYPE_LABEL[s.subtype] ?? s.subtype}</span>
            {s.magnet && <span className="rounded-full bg-fuchsia-50 px-2 py-0.5 text-[11px] font-medium text-fuchsia-700 ring-1 ring-inset ring-fuchsia-200">Magnet</span>}
          </div>
        </div>
        <button onClick={() => void select(null)} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
          <X className="size-5" />
        </button>
      </div>

      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-4">
        <div className="text-sm text-slate-600">
          <div>
            {s.address}
            {s.city ? `, ${s.city}` : ''} {s.zip ?? ''}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs">
            {s.distance_miles != null && <span className="font-medium text-slate-800">{s.distance_miles.toFixed(1)} mi from your location</span>}
            {s.phone && (
              <a href={`tel:${s.phone}`} className="inline-flex items-center gap-1 text-brand-600 hover:underline">
                <Phone className="size-3" /> {s.phone}
              </a>
            )}
            {s.website && (
              <a href={s.website} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">
                <ExternalLink className="size-3" /> Website
              </a>
            )}
          </div>
        </div>

        {explanation && (
          <div className="rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm text-slate-700">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-brand-700">Why it matched</div>
            <p>{explanation.why}</p>
            <p className="mt-1 text-xs text-slate-500">
              <span className="font-medium">Tradeoffs:</span> {explanation.tradeoffs}
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <Stat label="Grades served" value={gradeSpan(s.grade_low, s.grade_high, s.grades_text)} />
          <Stat label={s.enrollment ? 'Enrollment' : 'Capacity'} value={fmtNum(s.enrollment ?? s.capacity)} hint="Miami-Dade County GIS" />
          {s.student_teacher_ratio != null && <Stat label="Student : teacher" value={`${Math.round(s.student_teacher_ratio)} : 1`} hint="NCES CCD 2023-24" />}
          {s.frl_pct != null && <Stat label="Free/reduced lunch" value={fmtPct(s.frl_pct)} hint="NCES CCD 2023-24" />}
          {s.year_established && <Stat label="Established" value={s.year_established} />}
          {s.coed && <Stat label="Enrollment type" value={s.coed === 'coed' ? 'Co-ed' : s.coed === 'boys' ? 'Boys' : 'Girls'} />}
          {s.license_number && <Stat label="DCF license" value={s.license_number} hint={s.license_expires ? `Listed expiration ${s.license_expires}` : undefined} />}
        </div>

        {graded && (
          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Florida DOE 2025-26 accountability</h3>
            {s.fl_grade ? (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="ELA proficiency" value={fmtPct(s.ela_ach)} />
                  <Stat label="Math proficiency" value={fmtPct(s.math_ach)} />
                  <Stat label="Science" value={fmtPct(s.sci_ach)} />
                  <Stat label="Social studies" value={fmtPct(s.ss_ach)} />
                  <Stat label="ELA learning gains" value={fmtPct(s.ela_gains)} />
                  <Stat label="Math learning gains" value={fmtPct(s.math_gains)} />
                  {s.grad_rate != null && <Stat label="Graduation rate" value={fmtPct(s.grad_rate)} />}
                  {s.college_career_accel != null && <Stat label="College & career accel." value={fmtPct(s.college_career_accel)} />}
                  <Stat label="Points earned" value={fmtPct(s.pct_points)} hint="Percent of total possible accountability points" />
                  {s.pct_econ_disadvantaged != null && <Stat label="Econ. disadvantaged" value={fmtPct(s.pct_econ_disadvantaged)} />}
                </div>
                {history.length > 0 && (
                  <div className="mt-3">
                    <div className="mb-1 text-[11px] font-medium text-slate-400">Grade history</div>
                    <div className="flex flex-wrap gap-1.5">
                      {history.map(([y, g]) => (
                        <div key={y} className="flex flex-col items-center gap-0.5">
                          <GradeBadge grade={g} size="sm" />
                          <span className="text-[10px] text-slate-400">{y}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <div className="mt-2 flex gap-2 text-[11px] text-slate-500">
                  {s.fl_title_i && <span className="rounded bg-slate-100 px-1.5 py-0.5">Title I</span>}
                  {s.fl_school_type && <span className="rounded bg-slate-100 px-1.5 py-0.5">{{ '01': 'Elementary', '02': 'Middle', '03': 'High', '04': 'Combination' }[s.fl_school_type] ?? s.fl_school_type}</span>}
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-500">No 2025-26 school grade was published for this school.</p>
            )}
          </section>
        )}
        {!graded && (
          <p className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
            Florida does not publish school grades or test results for {s.category === 'private' ? 'private schools' : 'early childhood providers'}. Information shown comes from Miami-Dade County's public directory.
          </p>
        )}

        <div className="text-[11px] text-slate-400">
          Sources: Miami-Dade County Open Data{graded ? ', Florida DOE School Grades 2025-26, NCES Common Core of Data' : ''}.
        </div>
      </div>

      <div className="border-t border-slate-100 p-3">
        <button
          onClick={() => toggleCompare(s.id)}
          className={clsx(
            'inline-flex w-full items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition',
            inCompare ? 'bg-slate-100 text-slate-700 hover:bg-slate-200' : 'bg-slate-900 text-white hover:bg-slate-800',
          )}
        >
          <GitCompareArrows className="size-4" />
          {inCompare ? 'Remove from comparison' : compareIds.length >= 4 ? 'Comparison full (4 max)' : 'Add to comparison'}
        </button>
      </div>
    </aside>
  )
}
