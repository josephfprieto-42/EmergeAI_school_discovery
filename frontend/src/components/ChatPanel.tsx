import clsx from 'clsx'
import { RotateCcw, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { CATEGORY_META, gradeLabel, PRIORITY_LABEL } from '../lib/format'
import { useStore } from '../store'
import { SchoolCard } from './SchoolList'
import { Spinner } from './ui'

const SUGGESTIONS = [
  'We live in Coral Gables and have a 7-year-old. Looking for a small school with strong academics, ideally bilingual, within 3 miles.',
  'Need daycare for my 18-month-old near 33156, close to home.',
  'Looking for an A-rated public or charter high school with STEM programs near Doral.',
  'Catholic elementary school near Kendall for a kindergartner.',
]

export function ChatPanel() {
  const { chat, chatLoading, sendChat, resetChat, recommendation, prefs, config } = useStore()
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [chat, chatLoading])

  function submit(msg?: string) {
    const m = (msg ?? text).trim()
    if (!m || chatLoading) return
    setText('')
    void sendChat(m)
  }

  const expl = new globalThis.Map(recommendation?.explanations.map((e) => [e.school_id, e]) ?? [])

  return (
    <div className="flex h-full flex-col">
      <div className="scrollbar-thin flex-1 space-y-3 overflow-y-auto pr-1">
        {chat.length === 0 && (
          <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles className="size-4 text-brand-500" /> Describe what you're looking for
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Tell me where you live, your child's age or grade, and what matters most. I'll filter and rank real Miami-Dade providers using verified public data, then explain the tradeoffs.
            </p>
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

        {chat.map((m, i) => (
          <div key={i} className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div className={clsx('max-w-[90%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed shadow-sm', m.role === 'user' ? 'rounded-br-md bg-slate-900 text-white' : 'rounded-bl-md border border-slate-200 bg-white text-slate-700')}>
              {m.content}
            </div>
          </div>
        ))}
        {chatLoading && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner className="size-3" /> Filtering and ranking schools…
          </div>
        )}

        {recommendation && !chatLoading && (
          <div className="space-y-2">
            {prefs && (
              <div className="flex flex-wrap gap-1.5 px-1">
                {prefs.location_text && <Tag>Near {recommendation.origin_label ?? prefs.location_text}</Tag>}
                {prefs.child_grade != null && <Tag>Grade {gradeLabel(prefs.child_grade)}</Tag>}
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
              </div>
            )}
            <div className="px-1 text-[11px] text-slate-400">
              Ranked {recommendation.results.length} of {recommendation.candidates_considered} matching providers · {recommendation.llm_used ? 'AI explanations grounded in public data' : 'deterministic ranking'}
            </div>
            {recommendation.results.map((s, i) => (
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
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          rows={2}
          placeholder={chat.length ? 'Refine: "closer", "only A schools", "add private options"…' : 'e.g. "3rd grader near Brickell, strong math, small classes"'}
          className="flex-1 resize-none rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm outline-none ring-brand-500/30 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4"
        />
        <div className="flex flex-col gap-1">
          <button type="submit" disabled={chatLoading || !text.trim()} className="rounded-xl bg-brand-600 p-2.5 text-white shadow-sm hover:bg-brand-700 disabled:opacity-50" title="Send">
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

function Tag({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
      {color && <span className="size-1.5 rounded-full" style={{ background: color }} />}
      {children}
    </span>
  )
}
