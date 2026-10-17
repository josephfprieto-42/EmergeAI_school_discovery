import clsx from 'clsx'
import { MessageCircleQuestion, RotateCcw, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { CATEGORY_META, gradeLabel, PRIORITY_LABEL } from '../lib/format'
import { useStore } from '../store'
import type { Child, Household, Question } from '../types'
import { useIsTouch } from '../hooks/useMediaQuery'
import { SchoolCard } from './SchoolList'
import { Spinner } from './ui'

const SUGGESTIONS = [
  'Hi, I need help finding a school.',
  'Kindergarten near Kendall.',
  'We live in Coral Gables and have a 7-year-old. Looking for a small school with strong academics, ideally bilingual, within 3 miles.',
  'We both work downtown until 6, 2nd grader near Coral Gables, she does ballet in Coconut Grove.',
  'Need daycare for my 18-month-old near 33156, close to home.',
  'Looking for an A-rated public or charter high school with STEM programs near Doral.',
  'Catholic elementary school near Kendall for a kindergartner.',
]

const INTEREST_LABEL: Record<string, string> = { arts: 'Arts', stem: 'STEM', language: 'Language', sports: 'Sports' }
const NEAR_LABEL: Record<string, string> = { home: 'Near home', work: 'Near work', route: 'On the commute' }

function householdEmpty(h: Household | null): boolean {
  if (!h) return true
  return !(h.work_location_text || h.work_schedule_text || h.needs_after_school_care != null || h.activities?.length || h.activity_interests?.length)
}

export function ChatPanel({ onComposerFocus }: { onComposerFocus?: () => void } = {}) {
  const { chat, chatLoading, chatHydrated, sendChat, resetChat, recommendation, prefs, config, household, work, forgetHousehold } = useStore()
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const isTouch = useIsTouch()

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [chat, chatLoading])

  function submit(msg?: string) {
    const m = (msg ?? text).trim()
    if (!m || chatLoading || !chatHydrated) return
    setText('')
    void sendChat(m)
  }

  const expl = new globalThis.Map(recommendation?.explanations.map((e) => [e.school_id, e]) ?? [])

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {chat.length === 0 && (
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles className="size-4 text-accent" /> Describe what you're looking for
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Tell me where you live, your child's age or grade, and what matters most. I'll filter and rank real Miami-Dade providers using verified public data, then explain the tradeoffs.
            </p>
            {household && !householdEmpty(household) && (
              <div className="mt-3 rounded-xl bg-slate-50 py-2">
                <HouseholdTags household={household} workLabel={work?.label} onForget={forgetHousehold} />
              </div>
            )}
            <div className="mt-3 space-y-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => submit(s)} className="block w-full rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 transition hover:border-brand-200 hover:bg-brand-50 hover:text-slate-900">
                  “{s}”
                </button>
              ))}
            </div>
            {config && !config.features.llm && (
              <p className="mt-3 rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800">
                OpenAI key not set: using built-in keyword parsing and templated explanations. Add <code className="font-mono">OPENAI_API_KEY</code> for conversational understanding.
              </p>
            )}
          </div>
        )}

        {chat.map((m, i) => {
          // The latest assistant turn carries its question separately so the parent can tap an answer.
          const isLast = i === chat.length - 1
          const question = isLast && m.role === 'assistant' && !chatLoading ? recommendation?.question : null
          const body = question && m.content.endsWith(question.text) ? m.content.slice(0, -question.text.length).trim() : m.content
          return (
            <div key={i} className="space-y-2">
              {body && (
                <div className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div className={clsx('max-w-[90%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm', m.role === 'user' ? 'rounded-br-md bg-slate-900 text-white' : 'rounded-bl-md border border-slate-200 bg-white text-slate-700')}>
                    {body}
                  </div>
                </div>
              )}
              {question && <QuestionBubble question={question} onAnswer={(msg) => submit(msg)} disabled={chatLoading} />}
            </div>
          )
        })}
        {chatLoading && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner className="size-3" /> {recommendation?.stage === 'discovering' || !recommendation ? 'Thinking…' : 'Filtering and ranking schools…'}
          </div>
        )}

        {recommendation && !chatLoading && (
          <div className="space-y-2">
            {recommendation.changes && recommendation.changes.length > 0 && (
              <div className="px-1 text-[11px] text-slate-400">
                <span className="font-medium text-slate-500">Updated:</span> {recommendation.changes.join(' · ')}
              </div>
            )}
            {prefs && (
              <div className="flex flex-wrap gap-1.5 px-1">
                {prefs.location_text && <Tag>Near {recommendation.origin_label ?? prefs.location_text}</Tag>}
                {childTags(prefs).map((c) => (
                  <Tag key={c.grade}>{childLabel(c)}</Tag>
                ))}
                {prefs.radius_miles && <Tag>Within {prefs.radius_miles} mi</Tag>}
                {prefs.categories?.map((c) => (
                  <Tag key={c} color={CATEGORY_META[c].color}>
                    {CATEGORY_META[c].label}
                  </Tag>
                ))}
                {prefs.priorities?.map((p) => (
                  <Tag key={p}>{PRIORITY_LABEL[p] ?? p}</Tag>
                ))}
                {prefs.min_fl_grade && <Tag>{prefs.min_fl_grade}-rated or better</Tag>}
                {prefs.keywords?.map((k) => (
                  <Tag key={k}>{k}</Tag>
                ))}
                {prefs.prefer_near && <Tag>{NEAR_LABEL[prefs.prefer_near]}</Tag>}
              </div>
            )}
            <HouseholdTags household={household} workLabel={work?.label} onForget={forgetHousehold} />
            {recommendation.stage !== 'discovering' && (
              <>
                {recommendation.stage === 'preliminary' && prefs && (
                  <div className="mx-1 rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800">
                    First matches based on {preliminaryBasis(prefs, recommendation.origin_label)}. {preliminaryMissing(prefs, recommendation.origin_label)}
                  </div>
                )}
                <div className="px-1 text-[11px] text-slate-400">
                  {recommendation.groups?.length
                    ? `Separate lists · ${recommendation.llm_used ? 'AI explanations grounded in public data' : 'deterministic ranking'}`
                    : `Ranked ${recommendation.results.length} of ${recommendation.candidates_considered} matching providers · ${recommendation.llm_used ? 'AI explanations grounded in public data' : 'deterministic ranking'}`}
                </div>
              </>
            )}
            {recommendation.stage === 'discovering' ? null : recommendation.groups?.length
              ? recommendation.groups.map((g) => (
                  <section key={g.grade} className="space-y-2">
                    <div className="px-1 pt-1 text-xs font-semibold text-slate-700">
                      {childLabel(g)}
                      <span className="ml-2 font-normal text-slate-400">
                        Ranked {g.results.length} of {g.candidates_considered}
                      </span>
                    </div>
                    {g.results.map((s, i) => (
                      <SchoolCard key={`${g.grade}-${s.id}`} school={s} rank={i + 1} why={expl.get(s.id)?.why} />
                    ))}
                  </section>
                ))
              : recommendation.results.map((s, i) => (
                  <SchoolCard key={s.id} school={s} rank={i + 1} why={expl.get(s.id)?.why} />
                ))}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
        className="mt-3 flex items-end gap-2"
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // On touch keyboards Enter inserts a newline; send with the button instead.
            if (!isTouch && e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          onFocus={onComposerFocus}
          rows={2}
          placeholder={
            !chat.length
              ? 'e.g. "3rd grader near Brickell, strong math, small classes"'
              : recommendation?.question && recommendation.stage !== 'refined'
                ? 'Answer here, or tell me anything else that matters…'
                : 'Refine: "closer", "only A schools", "add private options"…'
          }
          className="flex-1 resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-base shadow-sm outline-none ring-accent/40 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 md:text-sm"
        />
        <div className="flex flex-col gap-1">
          <button type="submit" disabled={chatLoading || !chatHydrated || !text.trim()} className="rounded-xl bg-brand-600 p-2.5 text-white shadow-sm hover:bg-brand-700 disabled:opacity-50" title="Send">
            <Send className="size-4" />
          </button>
          {chat.length > 0 && (
            <button type="button" onClick={resetChat} className="rounded-xl border border-slate-200 bg-white p-2.5 text-slate-500 hover:bg-slate-50" title="Start over">
              <RotateCcw className="size-4" />
            </button>
          )}
        </div>
      </form>
    </div>
  )
}

function childTags(prefs: { children?: Child[]; child_grades?: number[]; child_grade?: number | null }): Child[] {
  if (prefs.children?.length) return prefs.children
  if (prefs.child_grades?.length) return prefs.child_grades.map((grade) => ({ grade }))
  if (prefs.child_grade != null) return [{ grade: prefs.child_grade }]
  return []
}

function childLabel(child: { grade: number; label?: string | null }) {
  const grade = child.grade <= 0 ? gradeLabel(child.grade) : `Grade ${gradeLabel(child.grade)}`
  return child.label ? `${grade} · ${child.label}` : grade
}

function preliminaryBasis(prefs: { children?: Child[]; location_text?: string | null }, originLabel: string | null): string {
  const parts: string[] = []
  if (prefs.children?.length) parts.push(prefs.children.map(childLabel).join(' and '))
  if (prefs.location_text || originLabel) parts.push(`your area (${originLabel ?? prefs.location_text})`)
  return parts.join(' and ') || 'what you told me'
}

function preliminaryMissing(prefs: { children?: Child[]; location_text?: string | null }, originLabel: string | null): string {
  if (!prefs.children?.length) return "Add your child's grade to sharpen them."
  if (!prefs.location_text && !originLabel) return 'Add where you live to rank by distance.'
  return ''
}

function QuestionBubble({ question, onAnswer, disabled }: { question: Question; onAnswer: (message: string) => void; disabled?: boolean }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-2 rounded-2xl rounded-bl-md border border-brand-200 bg-brand-50/60 px-3 py-2 shadow-sm">
        <div className="flex items-start gap-2 text-sm leading-relaxed text-slate-800">
          <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-accent" />
          <span>{question.text}</span>
        </div>
        {question.options.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {question.options.map((o) => (
              <button
                key={o.label}
                type="button"
                disabled={disabled}
                onClick={() => onAnswer(o.message)}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:border-brand-300 hover:bg-brand-50 hover:text-slate-900 disabled:opacity-50"
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function HouseholdTags({ household, workLabel, onForget }: { household: Household | null; workLabel?: string | null; onForget: () => Promise<void> }) {
  if (!household || householdEmpty(household)) return null
  return (
    <div className="space-y-1 px-1">
      <div className="flex flex-wrap gap-1.5">
        {household.work_location_text && <Tag>Work: {workLabel ?? household.work_location_text}</Tag>}
        {household.work_schedule_text && <Tag>{household.work_schedule_text}</Tag>}
        {household.needs_after_school_care === true && <Tag>Late pickup</Tag>}
        {household.needs_after_school_care === false && <Tag>Pickup covered</Tag>}
        {household.activities?.map((a) => (
          <Tag key={a.label}>
            {a.label}
            {a.location_text ? ` (${a.location_text})` : ''}
          </Tag>
        ))}
        {household.activity_interests
          ?.filter((i) => !household.activities?.length || i === 'sports')
          .map((i) => <Tag key={i}>{INTEREST_LABEL[i] ?? i}</Tag>)}
      </div>
      <div className="text-[11px] text-slate-400">
        Household remembered across searches ·{' '}
        <button type="button" onClick={() => void onForget()} className="underline decoration-dotted hover:text-slate-600">
          Forget
        </button>
      </div>
    </div>
  )
}

function Tag({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
      {color && <span className="size-1.5 rounded-full" style={{ background: color }} />}
      {children}
    </span>
  )
}
