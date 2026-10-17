import { LocateFixed, MapPin, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CATEGORY_META, GRADE_OPTIONS } from '../lib/format'
import { useStore } from '../store'
import type { Category } from '../types'
import { Chip } from './ui'

const CATS: Category[] = ['public', 'charter', 'private', 'early_childhood']
const RADII = [1, 2, 3, 5, 10]

export function FilterBar() {
  const { filters, setFilters, toggleCategory, toggleFlGrade, origin, setOrigin, locate, locateError } = useStore()
  const [loc, setLoc] = useState('')
  const [q, setQ] = useState(filters.q)
  const [locating, setLocating] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      if (q !== filters.q) setFilters({ q })
    }, 300)
    return () => clearTimeout(t)
  }, [q, filters.q, setFilters])

  async function onLocate(e: React.FormEvent) {
    e.preventDefault()
    if (!loc.trim()) return
    setLocating(true)
    await locate(loc.trim())
    setLocating(false)
  }

  function useMyLocation() {
    if (!navigator.geolocation) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setOrigin({ lat: p.coords.latitude, lng: p.coords.longitude, label: 'Current location' })
        setLocating(false)
      },
      () => setLocating(false),
      { timeout: 8000 },
    )
  }

  return (
    <div className="space-y-3">
      <form onSubmit={onLocate} className="flex gap-2">
        <div className="relative flex-1">
          <MapPin className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            value={loc}
            onChange={(e) => setLoc(e.target.value)}
            placeholder={origin ? origin.label : 'Home address, neighborhood, or ZIP'}
            className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-9 text-sm shadow-sm outline-none ring-brand-500/30 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4"
          />
          {origin && (
            <button type="button" onClick={() => setOrigin(null)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Clear location">
              <X className="size-4" />
            </button>
          )}
        </div>
        <button type="submit" disabled={locating} className="rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-60">
          {locating ? '…' : 'Go'}
        </button>
        <button type="button" onClick={useMyLocation} title="Use my location" className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 shadow-sm hover:bg-slate-50">
          <LocateFixed className="size-4" />
        </button>
      </form>
      {locateError && <div className="text-xs text-rose-600">{locateError}</div>}

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search school names (e.g. Montessori, Somerset, Coral)"
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm shadow-sm outline-none ring-brand-500/30 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4"
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {CATS.map((c) => (
          <Chip key={c} active={filters.categories.includes(c)} onClick={() => toggleCategory(c)} color={CATEGORY_META[c].color}>
            {CATEGORY_META[c].label}
          </Chip>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-400">Child's grade</span>
          <select
            value={filters.grade ?? ''}
            onChange={(e) => setFilters({ grade: e.target.value === '' ? null : Number(e.target.value) })}
            className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm shadow-sm outline-none focus:border-brand-500"
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
            onChange={(e) => setFilters({ radius: e.target.value === '' ? null : Number(e.target.value) })}
            className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm shadow-sm outline-none focus:border-brand-500 disabled:bg-slate-50 disabled:text-slate-400"
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

      <div>
        <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-400">Florida DOE grade (public & charter)</span>
        <div className="flex gap-1.5">
          {['A', 'B', 'C', 'D', 'F'].map((g) => (
            <Chip key={g} active={filters.flGrades.includes(g)} onClick={() => toggleFlGrade(g)}>
              {g}
            </Chip>
          ))}
        </div>
      </div>
    </div>
  )
}
