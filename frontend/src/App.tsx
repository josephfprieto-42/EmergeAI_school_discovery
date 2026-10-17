import clsx from 'clsx'
import { Compass, School, Sparkles } from 'lucide-react'
import { useEffect } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { CompareModal, CompareTray } from './components/Compare'
import { FilterBar } from './components/FilterBar'
import { MapView } from './components/MapView'
import { SchoolDetail } from './components/SchoolDetail'
import { SchoolList } from './components/SchoolList'
import { useStore } from './store'

export default function App() {
  const { mode, setMode, loadConfig, loadSchools, selected, schools } = useStore()

  useEffect(() => {
    void loadConfig()
    void loadSchools()
  }, [loadConfig, loadSchools])

  return (
    <div className="flex h-full flex-col">
      <header className="z-20 flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-xl bg-slate-900 text-white shadow-sm">
            <School className="size-4" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-bold tracking-tight text-slate-900">SchoolMatch Miami</div>
            <div className="text-[11px] text-slate-500">Infant care through 12th grade · Miami-Dade County</div>
          </div>
        </div>
        <nav className="flex rounded-xl bg-slate-100 p-1 text-xs font-medium">
          <button onClick={() => setMode('explore')} className={clsx('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition', mode === 'explore' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
            <Compass className="size-3.5" /> Explore
          </button>
          <button onClick={() => setMode('match')} className={clsx('inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 transition', mode === 'match' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
            <Sparkles className="size-3.5" /> Find my match
          </button>
        </nav>
        <div className="hidden text-[11px] text-slate-400 sm:block">{schools.length.toLocaleString()} providers loaded</div>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col-reverse sm:flex-row">
        <aside className="z-10 flex h-[48vh] w-full shrink-0 flex-col border-t border-slate-200 bg-slate-50 sm:h-auto sm:w-[420px] sm:border-r sm:border-t-0">
          <div className="scrollbar-thin flex-1 overflow-y-auto p-3">
            {mode === 'explore' ? (
              <div className="space-y-4">
                <FilterBar />
                <SchoolList />
              </div>
            ) : (
              <div className="h-full">
                <ChatPanel />
              </div>
            )}
          </div>
        </aside>

        <main className="relative min-h-0 flex-1">
          <MapView />
          <div className="pointer-events-none absolute inset-0 flex flex-col justify-between p-3">
            <div className="flex min-h-0 flex-1 justify-end">{selected && <div className="h-full w-full max-w-[400px]"><SchoolDetail /></div>}</div>
            <div className="mt-3 flex shrink-0 justify-center">
              <CompareTray />
            </div>
          </div>
          <Legend />
        </main>
      </div>
      <CompareModal />
    </div>
  )
}

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 hidden rounded-xl bg-white/90 px-3 py-2 text-[11px] text-slate-600 shadow backdrop-blur sm:block">
      <div className="flex gap-3">
        {[
          ['Public', '#2563eb'],
          ['Charter', '#7c3aed'],
          ['Private', '#d97706'],
          ['Early childhood', '#059669'],
        ].map(([l, c]) => (
          <span key={l} className="inline-flex items-center gap-1">
            <span className="size-2.5 rounded-full border border-white" style={{ background: c }} /> {l}
          </span>
        ))}
      </div>
    </div>
  )
}
