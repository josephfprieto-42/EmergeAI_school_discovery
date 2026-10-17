import clsx from 'clsx'
import { ExternalLink, Phone, Sparkles, X } from 'lucide-react'
import { useRef, useState, type MouseEvent } from 'react'
import { api } from '../api'
import { fmtNum, fmtPct, gradeSpan, SUBTYPE_LABEL } from '../lib/format'
import { useStore } from '../store'
import { CategoryPill, GradeBadge, Spinner, Stat } from './ui'

/** A new-tab link keeps its URL in the bottom-left status bar until the pointer leaves.
 * Drop it from hit testing on click so that preview clears immediately. */
function dismissStatusPreview(event: MouseEvent<HTMLAnchorElement>) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const link = event.currentTarget
  link.blur()
  const pointerType = 'pointerType' in event.nativeEvent ? event.nativeEvent.pointerType : undefined
  if (event.detail === 0 || pointerType === 'touch') return
  link.style.pointerEvents = 'none'
  const restore = () => {
    link.style.pointerEvents = ''
    document.removeEventListener('pointermove', onMove, true)
  }
  const onMove = (ev: PointerEvent) => {
    if (!link.isConnected) {
      document.removeEventListener('pointermove', onMove, true)
      return
    }
    const rect = link.getBoundingClientRect()
    const inside = ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top && ev.clientY <= rect.bottom
    if (!inside) restore()
  }
  document.addEventListener('pointermove', onMove, true)
}

/**
 * `card`: floating panel over the map (desktop). `sheet`: fills a mobile bottom sheet, which
 * already provides the rounded corners and shadow.
 */
export function SchoolDetail({ variant = 'card' }: { variant?: 'card' | 'sheet' }) {
  const { selected, select, recommendation, origin } = useStore()
  const [briefFor, setBriefFor] = useState<number | null>(null)
  const [answer, setAnswer] = useState<string | null>(null)
  const [briefError, setBriefError] = useState<string | null>(null)
  const [briefLoading, setBriefLoading] = useState(false)
  const requestSeq = useRef(0)
  if (!selected) return null
  const s = selected
  const waiting = briefLoading && briefFor === s.id
  const brief = briefFor === s.id ? answer : null
  const error = briefFor === s.id ? briefError : null

  function askAi() {
    if (waiting) return
    const id = s.id
    const seq = ++requestSeq.current
    setBriefFor(id)
    setAnswer(null)
    setBriefError(null)
    setBriefLoading(true)
    void api
      .askSchool(id, origin)
      .then((result) => {
        if (requestSeq.current !== seq) return
        setAnswer(result.answer)
      })
      .catch((err: Error) => {
        if (requestSeq.current !== seq) return
        setBriefError(err.message || 'Could not get a description right now.')
      })
      .finally(() => {
        if (requestSeq.current === seq) setBriefLoading(false)
      })
  }
  const graded = s.category === 'public' || s.category === 'charter'
  const explanation = recommendation?.explanations.find((e) => e.school_id === s.id)
  const history = s.grade_history ? Object.entries(s.grade_history).sort((a, b) => Number(b[0]) - Number(a[0])).slice(0, 6) : []

  return (
    <aside
      className={clsx(
        'pointer-events-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-white',
        variant === 'card' ? 'h-full rounded-2xl border border-slate-200 shadow-2xl' : 'h-full',
      )}
    >
      <div className={clsx('flex items-start gap-3 border-b border-slate-100 p-4', variant === 'sheet' && 'pt-1')}>
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
              <a href={s.website} target="_blank" rel="noreferrer" onClick={dismissStatusPreview} className="inline-flex items-center gap-1 text-brand-600 hover:underline">
                <ExternalLink className="size-3" /> Website
              </a>
            )}
          </div>
        </div>

        {explanation && (
          <div className="rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm text-slate-700">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">Why it matched</div>
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
        {(s.programs?.length || s.academics || s.sports?.length) ? (
          <section className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Programs and activities</h3>
            {s.programs && s.programs.length > 0 && (
              <div>
                <div className="mb-1 text-[11px] font-medium text-slate-400">M-DCPS magnet and choice programs</div>
                <ul className="space-y-1 text-sm text-slate-700">
                  {s.programs.map((program) => (
                    <li key={`${program.kind}-${program.name}`} className="flex flex-wrap items-center gap-2">
                      <span>{program.name}</span>
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                        {program.kind === 'magnet' ? 'Magnet' : 'Choice'}
                      </span>
                      {program.test_required && <span className="text-[10px] text-slate-400">Test required</span>}
                      {program.audition_required && <span className="text-[10px] text-slate-400">Audition required</span>}
                    </li>
                  ))}
                </ul>
                {s.programs.some((program) => program.admission_note) && (
                  <p className="mt-2 text-[11px] leading-snug text-slate-500">
                    {[...new Set(s.programs.map((program) => program.admission_note).filter(Boolean))].join(' ')}
                  </p>
                )}
              </div>
            )}
            {s.academics && (
              <div>
                <div className="mb-1 text-[11px] font-medium text-slate-400">Students enrolled, CRDC 2021-22</div>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    ['Advanced Placement', s.academics.ap_enrollment],
                    ['AP math', s.academics.ap_math],
                    ['AP science', s.academics.ap_science],
                    ['AP computer science', s.academics.ap_compsci],
                    ['AP language', s.academics.ap_language],
                    ['IB diploma', s.academics.ib_enrollment],
                    ['Gifted and talented', s.academics.gifted_enrollment],
                  ].filter((entry): entry is [string, number] => typeof entry[1] === 'number').map(([label, value]) => (
                    <Stat key={label} label={label} value={fmtNum(value)} />
                  ))}
                </div>
              </div>
            )}
            {s.sports && s.sports.length > 0 && (
              <div>
                <div className="mb-1 text-[11px] font-medium text-slate-400">FHSAA interscholastic sports</div>
                <div className="flex flex-wrap gap-1.5">
                  {s.sports.map((sport) => (
                    <span key={`${sport.sport}-${sport.team ?? ''}`} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                      {sport.sport}
                      {sport.team ? ` (${sport.team.toLowerCase()})` : ''}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        ) : null}

        {(s.assigned_zones?.length || s.attendance_levels?.length) ? (
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Attendance boundary</h3>
            {s.assigned_zones && s.assigned_zones.length > 0 ? (
              <p className="text-sm text-slate-700">
                This address is inside the published {s.assigned_zones.map((zone) => zone.level).join(' and ')} attendance area
                {s.assigned_zones[0].grade_low != null ? ` (grades ${s.assigned_zones[0].grade_low}–${s.assigned_zones[0].grade_high})` : ''}.
                Boundary residence is not the same as admission to a magnet or choice program.
              </p>
            ) : (
              <p className="text-sm text-slate-500">
                This campus has a published {s.attendance_levels?.join(' and ')} attendance area. Set a home location to see whether an address falls inside it.
              </p>
            )}
          </section>
        ) : null}

        {(s.religious != null || s.scholarship_programs?.length || s.accreditation || s.directory_survey_year) && (
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">Florida private-school survey</h3>
            <p className="mb-2 text-[11px] text-slate-400">
              School-reported{s.directory_survey_year ? `, survey year ${s.directory_survey_year}` : ''}. The Department of Education does not verify these answers. Scholarship participation is not a tuition amount.
            </p>
            <div className="space-y-1 text-sm text-slate-700">
              {s.religious === true && <div>Religious{s.denomination ? `: ${s.denomination}` : ''}</div>}
              {s.religious === false && <div>Reported as not religious</div>}
              {s.nonprofit != null && <div>{s.nonprofit ? 'Nonprofit' : 'Not reported as nonprofit'}</div>}
              {s.accreditation && <div>Accreditation: {s.accreditation}</div>}
              {s.scholarship_programs && s.scholarship_programs.length > 0 && <div>Participates in {s.scholarship_programs.join(', ')}</div>}
            </div>
          </section>
        )}

        {!graded && (
          <p className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
            Florida does not publish school grades or test results for {s.category === 'private' ? 'private schools' : 'early childhood providers'}. Information shown comes from Miami-Dade County's public directory.
          </p>
        )}

        <div className="text-[11px] text-slate-400">
          Sources: Miami-Dade County Open Data
          {graded ? ', Florida DOE School Grades 2025-26, NCES Common Core of Data' : ''}
          {s.programs?.length ? ', M-DCPS magnet and choice catalog' : ''}
          {s.academics ? ', CRDC 2021-22' : ''}
          {s.sports?.length ? ', FHSAA' : ''}
          {s.attendance_levels?.length ? ', M-DCPS attendance boundaries' : ''}
          {s.directory_survey_year ? ', Florida private-school directory' : ''}.
        </div>
      </div>

      <div className="border-t border-slate-100 p-3">
        {(waiting || brief || error) && (
          <div className="scrollbar-thin mb-3 max-h-64 overflow-y-auto rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm leading-relaxed text-slate-700">
            {waiting && (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <Spinner className="size-3" /> Reading this school's public record…
              </div>
            )}
            {error && <p className="text-rose-700">{error}</p>}
            {brief && <p className="whitespace-pre-wrap">{brief}</p>}
          </div>
        )}
        <button
          type="button"
          onClick={askAi}
          disabled={waiting}
          className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-2 py-2 text-xs font-medium text-white transition hover:bg-brand-700 disabled:opacity-40"
        >
          <Sparkles className="size-3.5" />
          {waiting ? 'Asking…' : brief ? 'Ask again' : 'Ask AI'}
        </button>
      </div>
    </aside>
  )
}
