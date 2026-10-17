import clsx from 'clsx'
import type { ReactNode } from 'react'
import { CATEGORY_META, FL_GRADE_STYLE } from '../lib/format'
import type { Category } from '../types'

export function CategoryPill({ category, className }: { category: Category; className?: string }) {
  const m = CATEGORY_META[category]
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset', m.bg, m.text, m.ring, className)}>
      <span className="size-1.5 rounded-full" style={{ background: m.color }} />
      {m.label}
    </span>
  )
}

export function GradeBadge({ grade, size = 'md' }: { grade: string | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  const cls = size === 'lg' ? 'size-12 text-2xl' : size === 'sm' ? 'size-6 text-xs' : 'size-8 text-sm'
  if (!grade) {
    return (
      <span className={clsx('inline-flex items-center justify-center rounded-lg bg-slate-100 font-semibold text-slate-400', cls)} title="No Florida DOE grade published">
        —
      </span>
    )
  }
  return (
    <span className={clsx('inline-flex items-center justify-center rounded-lg font-bold shadow-sm', cls, FL_GRADE_STYLE[grade] ?? 'bg-slate-300')} title={`Florida DOE 2025-26 school grade: ${grade}`}>
      {grade}
    </span>
  )
}

export function Chip({ active, onClick, children, color }: { active: boolean; onClick: () => void; children: ReactNode; color?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition',
        active ? 'border-brand-600 bg-brand-600 text-white shadow-sm' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50',
      )}
    >
      {color && <span className={clsx('size-2 rounded-full', active && 'ring-2 ring-white')} style={{ background: color }} />}
      {children}
    </button>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-3" title={hint}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-slate-800">{value}</div>
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <span className={clsx('inline-block size-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700', className)} />
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white/60 p-6 text-center">
      <div className="text-sm font-semibold text-slate-700">{title}</div>
      {body && <div className="mt-1 text-xs text-slate-500">{body}</div>}
    </div>
  )
}
