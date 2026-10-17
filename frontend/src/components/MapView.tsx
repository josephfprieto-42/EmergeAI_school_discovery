import { MarkerClusterer, SuperClusterAlgorithm } from '@googlemaps/markerclusterer'
import { APIProvider, Map, useMap, useMapsLibrary } from '@vis.gl/react-google-maps'
import { useEffect, useMemo, useRef } from 'react'
import { CATEGORY_META } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'

const MIAMI = { lat: 25.76, lng: -80.3 }

function markerContent(s: School, rank: number | null, state: 'normal' | 'selected' | 'hover'): HTMLElement {
  const el = document.createElement('div')
  const color = CATEGORY_META[s.category].color
  el.style.color = color
  el.style.position = 'relative'
  el.style.cursor = 'pointer'
  el.title = s.name
  if (rank != null) {
    el.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:9999px 9999px 9999px 0;transform:rotate(-45deg);background:${color};border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);color:white;font:700 12px/1 Inter,system-ui,sans-serif">${rank}</span></div>`
    el.style.transform = 'translateY(-6px)'
  } else {
    const size = state === 'normal' ? 10 : 14
    el.innerHTML = `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${color};border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`
  }
  if (state !== 'normal') {
    el.classList.add('marker-pulse')
    el.style.zIndex = '10'
  }
  return el
}

function Markers() {
  const map = useMap()
  const markerLib = useMapsLibrary('marker')
  const { schools, recommendation, selectedId, hoverId, select, setHover } = useStore()
  const clustererRef = useRef<MarkerClusterer | null>(null)
  const markersRef = useRef<globalThis.Map<number, google.maps.marker.AdvancedMarkerElement>>(new globalThis.Map())
  const pinnedRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([])

  const rankById = useMemo(() => {
    const m = new globalThis.Map<number, number>()
    recommendation?.results.forEach((r, i) => m.set(r.id, i + 1))
    return m
  }, [recommendation])

  // Clustered background markers for every school matching the filters.
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    clustererRef.current?.clearMarkers()
    markersRef.current.clear()
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    for (const s of schools) {
      if (rankById.has(s.id)) continue
      const m = new AdvancedMarkerElement({ position: { lat: s.lat, lng: s.lon }, content: markerContent(s, null, 'normal') })
      m.addListener('click', () => void select(s.id))
      const content = m.content as HTMLElement
      content.addEventListener('mouseenter', () => setHover(s.id))
      content.addEventListener('mouseleave', () => setHover(null))
      markersRef.current.set(s.id, m)
      markers.push(m)
    }
    if (!clustererRef.current) {
      clustererRef.current = new MarkerClusterer({
        map,
        algorithm: new SuperClusterAlgorithm({ radius: 70, maxZoom: 14 }),
        renderer: {
          render: ({ count, position }) => {
            const el = document.createElement('div')
            const size = count > 200 ? 46 : count > 50 ? 40 : 34
            el.innerHTML = `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:rgba(15,23,42,.85);color:white;display:flex;align-items:center;justify-content:center;font:600 12px Inter,system-ui,sans-serif;border:2px solid white;box-shadow:0 2px 8px rgba(0,0,0,.3)">${count}</div>`
            return new AdvancedMarkerElement({ position, content: el, zIndex: 1000 + count })
          },
        },
      })
    }
    clustererRef.current.addMarkers(markers)
    return () => {
      clustererRef.current?.clearMarkers()
    }
  }, [map, markerLib, schools, rankById, select, setHover])

  // Numbered pins for recommendation results (never clustered).
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    pinnedRef.current.forEach((m) => (m.map = null))
    pinnedRef.current = []
    for (const s of recommendation?.results ?? []) {
      const m = new AdvancedMarkerElement({ map, position: { lat: s.lat, lng: s.lon }, content: markerContent(s, rankById.get(s.id) ?? null, 'normal'), zIndex: 5000 })
      m.addListener('click', () => void select(s.id))
      pinnedRef.current.push(m)
    }
    return () => {
      pinnedRef.current.forEach((m) => (m.map = null))
    }
  }, [map, markerLib, recommendation, rankById, select])

  // Selected / hover styling.
  useEffect(() => {
    const ids = [selectedId, hoverId].filter((x): x is number => x != null)
    const touched: google.maps.marker.AdvancedMarkerElement[] = []
    for (const id of ids) {
      const m = markersRef.current.get(id)
      const s = schools.find((x) => x.id === id)
      if (m && s) {
        m.content = markerContent(s, null, id === selectedId ? 'selected' : 'hover')
        m.zIndex = 4000
        touched.push(m)
      }
    }
    return () => {
      for (const m of touched) {
        const id = [...markersRef.current.entries()].find(([, v]) => v === m)?.[0]
        const s = schools.find((x) => x.id === id)
        if (s) {
          m.content = markerContent(s, null, 'normal')
          m.zIndex = null
        }
      }
    }
  }, [selectedId, hoverId, schools])

  return null
}

function HomeAndRadius() {
  const map = useMap()
  const markerLib = useMapsLibrary('marker')
  const { origin, filters, fitRequest, recommendation, selected } = useStore()
  const circleRef = useRef<google.maps.Circle | null>(null)
  const homeRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null)

  useEffect(() => {
    if (!map || !markerLib) return
    if (homeRef.current) homeRef.current.map = null
    circleRef.current?.setMap(null)
    if (!origin) return
    const el = document.createElement('div')
    el.innerHTML = `<div style="display:flex;align-items:center;gap:6px;background:white;border-radius:9999px;padding:4px 10px 4px 6px;box-shadow:0 2px 10px rgba(0,0,0,.25);font:600 12px Inter,system-ui,sans-serif;color:#0f172a"><span style="width:14px;height:14px;border-radius:9999px;background:#0f172a;border:3px solid white;box-shadow:0 0 0 2px #0f172a"></span>Home</div>`
    homeRef.current = new markerLib.AdvancedMarkerElement({ map, position: origin, content: el, zIndex: 9000 })
    if (filters.radius) {
      circleRef.current = new google.maps.Circle({
        map,
        center: origin,
        radius: filters.radius * 1609.34,
        fillColor: '#2563eb',
        fillOpacity: 0.06,
        strokeColor: '#2563eb',
        strokeOpacity: 0.5,
        strokeWeight: 1.5,
        clickable: false,
      })
    }
  }, [map, markerLib, origin, filters.radius])

  useEffect(() => {
    if (!map || fitRequest === 0) return
    const b = new google.maps.LatLngBounds()
    let n = 0
    if (recommendation?.results.length) {
      recommendation.results.forEach((s) => {
        b.extend({ lat: s.lat, lng: s.lon })
        n++
      })
      if (origin) b.extend(origin)
    } else if (origin) {
      const r = (filters.radius ?? 3) * 1609.34
      const c = new google.maps.Circle({ center: origin, radius: r })
      const cb = c.getBounds()
      if (cb) {
        b.union(cb)
        n++
      }
    }
    if (n > 0) map.fitBounds(b, 60)
  }, [map, fitRequest, recommendation, origin, filters.radius])

  useEffect(() => {
    if (!map || !selected) return
    const p = { lat: selected.lat, lng: selected.lon }
    const bounds = map.getBounds()
    if (!bounds || !bounds.contains(p)) map.panTo(p)
  }, [map, selected])

  return null
}

function GoogleMapView({ apiKey, mapId }: { apiKey: string; mapId: string }) {
  return (
    <APIProvider apiKey={apiKey} libraries={['marker']}>
      <Map
        defaultCenter={MIAMI}
        defaultZoom={10}
        mapId={mapId}
        gestureHandling="greedy"
        disableDefaultUI
        zoomControl
        clickableIcons={false}
        className="h-full w-full"
        onClick={() => void useStore.getState().select(null)}
      >
        <Markers />
        <HomeAndRadius />
      </Map>
    </APIProvider>
  )
}

// ----------------------------------------------------------------------------------
// Fallback: a simple projected plot used only when no Google Maps key is configured.
// ----------------------------------------------------------------------------------
const FB = { s: 25.3, w: -80.65, n: 26.0, e: -80.08 }

function FallbackMap() {
  const { schools, recommendation, selectedId, hoverId, select, setHover, origin, filters } = useStore()
  const W = 1000
  const H = Math.round((W * (FB.n - FB.s)) / ((FB.e - FB.w) * Math.cos((25.7 * Math.PI) / 180)))
  const px = (lon: number) => ((lon - FB.w) / (FB.e - FB.w)) * W
  const py = (lat: number) => ((FB.n - lat) / (FB.n - FB.s)) * H
  const ranked = new globalThis.Map<number, number>()
  recommendation?.results.forEach((r, i) => ranked.set(r.id, i + 1))
  const radiusPx = origin && filters.radius ? (filters.radius / 69) * (H / (FB.n - FB.s)) : 0
  // Zoom the viewBox to the visible points (plus home/radius) with padding.
  const focus = recommendation?.results.length ? recommendation.results : schools
  let vb = `0 0 ${W} ${H}`
  if (focus.length) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    const ext = (x: number, y: number, r = 0) => { x0 = Math.min(x0, x - r); y0 = Math.min(y0, y - r); x1 = Math.max(x1, x + r); y1 = Math.max(y1, y + r) }
    focus.forEach((s) => ext(px(s.lon), py(s.lat)))
    if (origin) ext(px(origin.lng), py(origin.lat), radiusPx)
    const pad = Math.max(20, (x1 - x0) * 0.15, (y1 - y0) * 0.15)
    const vw = Math.max(80, x1 - x0 + pad * 2), vh = Math.max(80, y1 - y0 + pad * 2)
    vb = `${x0 - pad} ${y0 - pad} ${vw} ${vh}`
  }
  return (
    <div className="relative h-full w-full bg-[#e8eef5]">
      <svg viewBox={vb} className="h-full w-full" preserveAspectRatio="xMidYMid meet" onClick={() => void select(null)}>
        <rect width={W} height={H} fill="#e8eef5" />
        {origin && radiusPx > 0 && <circle cx={px(origin.lng)} cy={py(origin.lat)} r={radiusPx} fill="#2563eb" fillOpacity={0.07} stroke="#2563eb" strokeOpacity={0.5} strokeWidth={1.5} />}
        {schools.map((s) => {
          const r = ranked.get(s.id)
          const active = s.id === selectedId || s.id === hoverId
          return (
            <g key={s.id} onClick={(e) => { e.stopPropagation(); void select(s.id) }} onMouseEnter={() => setHover(s.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              <circle cx={px(s.lon)} cy={py(s.lat)} r={r ? 9 : active ? 6 : 3} fill={CATEGORY_META[s.category].color} stroke="white" strokeWidth={r || active ? 2 : 0.8} opacity={r || active ? 1 : 0.8} />
              {r && (
                <text x={px(s.lon)} y={py(s.lat) + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
                  {r}
                </text>
              )}
              <title>{s.name}</title>
            </g>
          )
        })}
        {origin && (
          <g>
            <circle cx={px(origin.lng)} cy={py(origin.lat)} r={7} fill="#0f172a" stroke="white" strokeWidth={2.5} />
          </g>
        )}
      </svg>
      <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full bg-slate-900/85 px-3 py-1.5 text-xs text-white shadow">
        Google Maps is off — add <code className="font-mono">GOOGLE_MAPS_BROWSER_KEY</code> to backend/.env for the interactive map
      </div>
    </div>
  )
}

export function MapView() {
  const config = useStore((s) => s.config)
  if (!config) return <div className="h-full w-full animate-pulse bg-slate-100" />
  if (config.maps_browser_key) return <GoogleMapView apiKey={config.maps_browser_key} mapId={config.map_id ?? 'DEMO_MAP_ID'} />
  return <FallbackMap />
}
