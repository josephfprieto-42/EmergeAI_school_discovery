import { APIProvider } from '@vis.gl/react-google-maps'
import clsx from 'clsx'
import { Compass, School, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { BottomSheet, type SheetSnap } from './components/BottomSheet'
import { ChatPanel } from './components/ChatPanel'
import { LocationPicker } from './components/LocationPicker'
import { MapView } from './components/MapView'
import { FilterBar } from './components/FilterBar'
import { SchoolDetail } from './components/SchoolDetail'
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

function MapStage() {
  const isDesktop = useIsDesktop()
  const { mode, selected, selectedId, select, chat, mapInsetBottom, setMapInsetBottom } = useStore()
  const [chatSnap, setChatSnap] = useState<SheetSnap>('half')
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

  const showChatSheet = !isDesktop && mode === 'match'
  const showDetailSheet = !isDesktop && !!selected
  const sheetCoversMap = showDetailSheet ? detailSnap === 'full' : showChatSheet && chatSnap === 'full'
  // Desktop zoom control is two 40px buttons inset from the corner, about 104px tall.
  const legendBottom = isDesktop ? 112 : Math.max(12, mapInsetBottom + 12)

  useEffect(() => {
    if (isDesktop || (!showChatSheet && !showDetailSheet)) setMapInsetBottom(0)
  }, [isDesktop, showChatSheet, showDetailSheet, setMapInsetBottom])

  return (
    <main className="relative min-h-0 flex-1 overflow-clip">
      <MapView />

      {mode === 'explore' ? (
        <ExploreOverlay />
      ) : (
        isDesktop && (
          <div className="absolute bottom-3 left-3 top-3 z-10 flex w-[400px] flex-col overflow-hidden rounded-2xl border border-brand-100 bg-brand-50 p-3 shadow-xl">
            <ChatPanel />
          </div>
        )
      )}

      {isDesktop && selected && (
        <div className="pointer-events-none absolute inset-y-3 right-3 z-20 flex w-full max-w-[400px] flex-col">
          <SchoolDetail />
        </div>
      )}

      {!sheetCoversMap && <Legend selectedOpen={isDesktop && !!selected} bottom={legendBottom} />}

      {showChatSheet && (
        <BottomSheet
          snap={chatSnap}
          onSnapChange={setChatSnap}
          peekHeight={PEEK}
          onHeightChange={setMapInsetBottom}
          label="Find my match"
        >
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto p-3">
            <div className="h-full">
              <ChatPanel onComposerFocus={() => setChatSnap('full')} />
            </div>
          </div>
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

function ExploreOverlay() {
  return (
    <div className="pointer-events-none absolute left-3 top-3 z-10 flex max-h-[calc(100%-1.5rem)] w-[min(100%-1.5rem,400px)] flex-col">
      <div className="pointer-events-auto flex min-h-0 flex-col overflow-hidden rounded-2xl border border-brand-100 bg-brand-50 shadow-xl">
        <div className="shrink-0 border-b border-slate-200 p-3">
          <LocationPicker />
        </div>
        <div className="scrollbar-thin max-h-[min(46vh,420px)] overflow-y-auto p-3">
          <FilterBar />
        </div>
      </div>
    </div>
  )
}

function Legend({ selectedOpen, bottom }: { selectedOpen: boolean; bottom: number }) {
  return (
    <div
      className={clsx(
        'pointer-events-none absolute right-3 z-10 flex items-center gap-2 whitespace-nowrap rounded-xl bg-white px-2.5 py-1.5 text-[11px] text-slate-700 shadow md:text-xs',
        selectedOpen && 'md:right-[424px]',
      )}
      style={{ bottom }}
    >
      <span className="font-medium text-slate-500">School type</span>
      {Object.entries(CATEGORY_META).map(([key, m]) => (
        <span key={key} className="inline-flex items-center gap-1">
          <span className="size-3 rounded-full border border-slate-200" style={{ background: m.color }} />
          <span className="md:hidden">{m.short}</span>
          <span className="hidden md:inline">{m.label}</span>
        </span>
      ))}
    </div>
  )
}
