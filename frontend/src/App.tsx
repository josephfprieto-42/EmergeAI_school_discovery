import { APIProvider } from '@vis.gl/react-google-maps'
import clsx from 'clsx'
import { ChevronDown, Compass, School, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { BottomSheet, type SheetSnap } from './components/BottomSheet'
import { ChatPanel } from './components/ChatPanel'
import { CompareModal, CompareTray } from './components/Compare'
import { LocationPicker } from './components/LocationPicker'
import { MapView } from './components/MapView'
import { FilterBar } from './components/FilterBar'
import { SchoolDetail } from './components/SchoolDetail'
import { SchoolList } from './components/SchoolList'
import { useIsDesktop } from './hooks/useMediaQuery'
import { CATEGORY_META } from './lib/format'
import { useStore } from './store'

export default function App() {
  const { config, loadConfig, loadSchools, restoreSession } = useStore()

  useEffect(() => {
    void loadConfig()
    void loadSchools()
    void restoreSession()
  }, [loadConfig, loadSchools, restoreSession])

  if (config?.maps_browser_key) {
    return (
      <APIProvider apiKey={config.maps_browser_key} libraries={['marker', 'places']}>
        <Shell />
      </APIProvider>
    )
  }
  return <Shell />
}

function Shell() {
  return (
    <div className="flex h-full flex-col bg-white pt-[env(safe-area-inset-top)]">
      <Header />
      <MapStage />
      <CompareModal />
    </div>
  )
}

function Header() {
  const { mode, setMode, schools } = useStore()
  return (
    <header className="z-20 flex h-14 shrink-0 items-center justify-between gap-2 border-b-2 border-accent bg-brand-700 px-3 md:px-4">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-white/15 text-white ring-1 ring-accent">
          <School className="size-4" />
        </div>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-bold tracking-tight text-white">SchoolMatch Miami</div>
          <div className="hidden text-[11px] text-white/70 md:block">Infant care through 12th grade · Miami-Dade County</div>
        </div>
      </div>
      <nav className="flex shrink-0 rounded-xl bg-white/15 p-1 text-xs font-medium">
        <button onClick={() => setMode('explore')} className={clsx('inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 transition md:px-3', mode === 'explore' ? 'bg-white text-brand-700 shadow-sm' : 'text-white/75 hover:text-white')}>
          <Compass className="size-3.5" /> Explore
        </button>
        <button onClick={() => setMode('match')} className={clsx('inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 transition md:px-3', mode === 'match' ? 'bg-white text-brand-700 shadow-sm' : 'text-white/75 hover:text-white')}>
          <Sparkles className="size-3.5" />
          <span className="md:hidden">Match</span>
          <span className="hidden md:inline">Find my match</span>
        </button>
      </nav>
      <div className="hidden text-[11px] text-white/70 lg:block">{schools.length.toLocaleString()} providers loaded</div>
    </header>
  )
}

const PEEK = 108
const PEEK_WITH_TRAY = 164

function MapStage() {
  const isDesktop = useIsDesktop()
  const { mode, selected, selectedId, select, compareIds, chat, setMapInsetBottom } = useStore()
  const [resultsOpen, setResultsOpen] = useState(false)
  const [chatSnap, setChatSnap] = useState<SheetSnap>('half')
  const [resultsSnap, setResultsSnap] = useState<SheetSnap>('half')
  const [detailSnap, setDetailSnap] = useState<SheetSnap>('half')

  const [tracked, setTracked] = useState({ mode, chatLen: chat.length })
  if (tracked.mode !== mode || tracked.chatLen !== chat.length) {
    setTracked({ mode, chatLen: chat.length })
    if (!isDesktop && mode === 'match') setChatSnap('half')
  }

  const [trackedSelected, setTrackedSelected] = useState(selectedId)
  if (trackedSelected !== selectedId) {
    setTrackedSelected(selectedId)
    if (selectedId != null) setDetailSnap('half')
  }

  const showResultsSheet = !isDesktop && mode === 'explore' && resultsOpen
  const showChatSheet = !isDesktop && mode === 'match'
  const showDetailSheet = !isDesktop && !!selected
  const floatCompare = compareIds.length > 0 && !showResultsSheet && !showChatSheet

  useEffect(() => {
    if (isDesktop || (!showResultsSheet && !showChatSheet && !showDetailSheet)) setMapInsetBottom(0)
  }, [isDesktop, showResultsSheet, showChatSheet, showDetailSheet, setMapInsetBottom])

  return (
    <main className="relative min-h-0 flex-1 overflow-clip">
      <MapView />

      {mode === 'explore' ? (
        <ExploreOverlay resultsOpen={resultsOpen} onToggleResults={() => setResultsOpen((open) => !open)} showList={isDesktop} />
      ) : (
        isDesktop && (
          <div className="absolute bottom-3 left-3 top-3 z-10 flex w-[400px] flex-col overflow-hidden rounded-2xl border border-brand-100 bg-brand-50 shadow-xl">
            <div className="shrink-0 border-b border-slate-200 p-3">
              <LocationPicker />
            </div>
            <div className="flex min-h-0 flex-1 flex-col p-3">
              <ChatPanel />
            </div>
          </div>
        )
      )}

      {isDesktop && selected && (
        <div className="pointer-events-none absolute inset-y-3 right-3 z-20 flex w-full max-w-[400px] flex-col">
          <SchoolDetail />
        </div>
      )}

      {floatCompare && (
        <div className="pointer-events-none absolute inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-20 flex justify-center">
          <CompareTray />
        </div>
      )}

      {isDesktop && <Legend selectedOpen={!!selected} />}

      {showChatSheet && (
        <BottomSheet
          snap={chatSnap}
          onSnapChange={setChatSnap}
          peekHeight={compareIds.length ? PEEK_WITH_TRAY : PEEK}
          header={compareIds.length ? <CompareTray /> : undefined}
          onHeightChange={setMapInsetBottom}
          label="Find my match"
        >
          <div className="shrink-0 border-b border-slate-200 px-3 pb-3">
            <LocationPicker />
          </div>
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-3">
            <div className="h-full">
              <ChatPanel onComposerFocus={() => setChatSnap('full')} />
            </div>
          </div>
        </BottomSheet>
      )}

      {showResultsSheet && (
        <BottomSheet
          snap={resultsSnap}
          onSnapChange={setResultsSnap}
          peekHeight={compareIds.length ? PEEK_WITH_TRAY : PEEK}
          header={compareIds.length ? <CompareTray /> : undefined}
          onHeightChange={setMapInsetBottom}
          onDismiss={() => setResultsOpen(false)}
          label="School results"
        >
          <SchoolList />
        </BottomSheet>
      )}

      {showDetailSheet && (
        <BottomSheet snap={detailSnap} onSnapChange={setDetailSnap} peekHeight={PEEK} zIndex={30} onDismiss={() => void select(null)} onHeightChange={setMapInsetBottom} className="bg-white" label="School details">
          <SchoolDetail variant="sheet" />
        </BottomSheet>
      )}
    </main>
  )
}

function ExploreOverlay({ resultsOpen, onToggleResults, showList }: { resultsOpen: boolean; onToggleResults: () => void; showList: boolean }) {
  const { schools, schoolsLoading } = useStore()
  const count = schoolsLoading ? 'Loading schools' : `${schools.length.toLocaleString()} schools`
  return (
    <div className={clsx('pointer-events-none absolute left-3 top-3 z-10 flex max-h-[calc(100%-1.5rem)] w-[min(100%-1.5rem,400px)] flex-col', showList && resultsOpen && 'bottom-3')}>
      <div className="pointer-events-auto flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-brand-100 bg-brand-50 shadow-xl">
        <div className="shrink-0 border-b border-slate-200 p-3">
          <LocationPicker />
        </div>
        <div className={clsx('scrollbar-thin shrink-0 overflow-y-auto p-3', resultsOpen ? 'max-h-[38%]' : 'max-h-[min(46vh,420px)]')}>
          <FilterBar />
        </div>
        <button type="button" aria-expanded={resultsOpen} onClick={onToggleResults} className="flex shrink-0 items-center justify-between gap-2 border-t border-slate-200 px-3 py-2.5 text-left text-sm font-medium text-slate-800 hover:bg-white/60">
          <span>{count}</span>
          <ChevronDown className={clsx('size-4 shrink-0 text-slate-400 transition', resultsOpen && 'rotate-180')} />
        </button>
        {showList && resultsOpen && (
          <div className="flex min-h-0 flex-1 flex-col border-t border-slate-200 bg-white">
            <SchoolList />
          </div>
        )}
      </div>
    </div>
  )
}

function Legend({ selectedOpen }: { selectedOpen: boolean }) {
  return (
    <div className={clsx('pointer-events-none absolute bottom-3 z-10 rounded-xl bg-white/90 px-3 py-2 text-[11px] text-slate-600 shadow backdrop-blur', selectedOpen ? 'right-[424px]' : 'right-3')}>
      <div className="flex gap-3">
        {Object.values(CATEGORY_META).map((m) => (
          <span key={m.label} className="inline-flex items-center gap-1">
            <span className="size-2.5 rounded-full border border-white" style={{ background: m.color }} /> {m.label}
          </span>
        ))}
      </div>
    </div>
  )
}
