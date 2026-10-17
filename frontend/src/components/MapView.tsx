import { MarkerClusterer, SuperClusterAlgorithm } from '@googlemaps/markerclusterer'
import { Map, useMap, useMapsLibrary } from '@vis.gl/react-google-maps'
import { useEffect, useMemo, useRef } from 'react'
import { useIsDesktop } from '../hooks/useMediaQuery'
import { CATEGORY_META } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'

const MIAMI = { lat: 25.76, lng: -80.3 }
const BRAND_BLUE = CATEGORY_META.public.color

function bindMarkerHover(el: HTMLElement, id: number, setHover: (id: number | null) => void) {
  el.addEventListener('mouseenter', () => setHover(id))
  el.addEventListener('mouseleave', () => setHover(null))
}

/** White ring thickness. The colored center stays put; selection only adds white. */
function ringWidth(state: 'normal' | 'selected' | 'hover'): number {
  if (state === 'selected') return 7
  if (state === 'hover') return 3
  return 2
}

function markerContent(s: School, rank: number | null, state: 'normal' | 'selected' | 'hover', muted = false): HTMLElement {
  const el = document.createElement('div')
  const color = CATEGORY_META[s.category].color
  el.style.cursor = 'pointer'
  el.title = s.name
  const ring = ringWidth(state)
  if (rank != null) {
    // Border sits inside the box, so grow the pin with the ring to keep the colored shape.
    const size = 24 + ring * 2
    el.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:9999px 9999px 9999px 0;transform:rotate(-45deg);background:${color};border:${ring}px solid white;box-sizing:border-box;box-shadow:0 2px 6px rgba(0,0,0,.35)"><span style="transform:rotate(45deg);color:white;font:700 12px/1 Inter,system-ui,sans-serif">${rank}</span></div>`
    el.style.transform = 'translateY(-6px)'
  } else {
    const dot = muted && state === 'normal' ? 6 : 14
    const opacity = muted && state === 'normal' ? 0.35 : 1
    el.innerHTML = `<div style="padding:${ring}px;border-radius:9999px;background:white;box-shadow:0 1px 3px rgba(0,0,0,.4);opacity:${opacity};line-height:0"><div style="width:${dot}px;height:${dot}px;border-radius:9999px;background:${color}"></div></div>`
  }
  return el
}

function Markers() {
  const map = useMap()
  const markerLib = useMapsLibrary('marker')
  const { schools, recommendation, selectedId, hoverId, select, setHover, mode } = useStore()
  const clustererRef = useRef<MarkerClusterer | null>(null)
  const markersRef = useRef<globalThis.Map<number, google.maps.marker.AdvancedMarkerElement>>(new globalThis.Map())
  const pinnedRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([])
  const pinnedByIdRef = useRef<globalThis.Map<number, google.maps.marker.AdvancedMarkerElement>>(new globalThis.Map())

  const picks = useMemo(() => (recommendation?.results ?? []).slice(0, 5), [recommendation])
  const rankById = useMemo(() => {
    const m = new globalThis.Map<number, number>()
    picks.forEach((r, i) => m.set(r.id, i + 1))
    return m
  }, [picks])
  const muteOthers = mode === 'match' && rankById.size > 0

  // Clustered background markers for every school matching the filters.
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    clustererRef.current?.clearMarkers()
    markersRef.current.clear()
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    for (const s of schools) {
      if (rankById.has(s.id)) continue
      const m = new AdvancedMarkerElement({
        position: { lat: s.lat, lng: s.lon },
        content: markerContent(s, null, 'normal', muteOthers),
        anchorLeft: '-50%',
        anchorTop: '-50%',
      })
      m.addListener('click', () => void select(s.id))
      bindMarkerHover(m.content as HTMLElement, s.id, setHover)
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
  }, [map, markerLib, schools, rankById, select, setHover, muteOthers])

  // Numbered pins for recommendation results (never clustered).
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    pinnedRef.current.forEach((m) => (m.map = null))
    pinnedRef.current = []
    pinnedByIdRef.current.clear()
    for (const s of picks) {
      const rank = rankById.get(s.id) ?? null
      const m = new AdvancedMarkerElement({ map, position: { lat: s.lat, lng: s.lon }, content: markerContent(s, rank, 'normal'), zIndex: 5000 })
      m.addListener('click', () => void select(s.id))
      pinnedRef.current.push(m)
      pinnedByIdRef.current.set(s.id, m)
    }
    return () => {
      pinnedRef.current.forEach((m) => (m.map = null))
    }
  }, [map, markerLib, picks, rankById, select])

  // Selected / hover styling. The colored dot stays the same size; only the white ring grows.
  useEffect(() => {
    const ids = [...new Set([selectedId, hoverId].filter((x): x is number => x != null))]
    const touched: { marker: google.maps.marker.AdvancedMarkerElement; id: number; rank: number | null }[] = []
    for (const id of ids) {
      const state = id === selectedId ? 'selected' : 'hover'
      const clustered = markersRef.current.get(id)
      const school = schools.find((x) => x.id === id)
      if (clustered && school) {
        clustered.content = markerContent(school, null, state, false)
        bindMarkerHover(clustered.content as HTMLElement, id, setHover)
        clustered.zIndex = 4000
        touched.push({ marker: clustered, id, rank: null })
      }
      const pinned = pinnedByIdRef.current.get(id)
      const pick = picks.find((x) => x.id === id)
      if (pinned && pick) {
        const rank = rankById.get(id) ?? null
        pinned.content = markerContent(pick, rank, state, false)
        pinned.zIndex = 4000
        touched.push({ marker: pinned, id, rank })
      }
    }
    return () => {
      for (const t of touched) {
        const school = (t.rank != null ? picks : schools).find((x) => x.id === t.id)
        if (!school) continue
        t.marker.content = markerContent(school, t.rank, 'normal', t.rank == null && muteOthers)
        if (t.rank == null) bindMarkerHover(t.marker.content as HTMLElement, t.id, setHover)
        t.marker.zIndex = t.rank != null ? 5000 : null
      }
    }
  }, [selectedId, hoverId, schools, picks, rankById, muteOthers, setHover])

  return null
}

/** Bottom-sheet inset, capped so padding never exceeds the visible map. */
function usableInset(map: google.maps.Map, inset: number): number {
  const h = map.getDiv().clientHeight || 0
  return Math.max(0, Math.min(inset, Math.round(h * 0.55)))
}

function pinContent(label: string, dotColor: string): HTMLElement {
  const el = document.createElement('div')
  el.innerHTML = `<div style="display:flex;align-items:center;gap:6px;background:white;border-radius:9999px;padding:4px 10px 4px 6px;box-shadow:0 2px 10px rgba(0,0,0,.25);font:600 12px Inter,system-ui,sans-serif;color:#0f172a"><span style="width:14px;height:14px;border-radius:9999px;background:${dotColor};border:3px solid white;box-shadow:0 0 0 2px ${dotColor}"></span>${label}</div>`
  return el
}

/** Work pin and a dashed home-to-work line, plus one pin per activity place. */
function HouseholdPins() {
  const map = useMap()
  const markerLib = useMapsLibrary('marker')
  const { origin, work, recommendation } = useStore()
  const pinsRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([])
  const lineRef = useRef<google.maps.Polyline | null>(null)
  const activityPoints = useMemo(() => recommendation?.activity_points ?? [], [recommendation])

  useEffect(() => {
    if (!map || !markerLib) return
    pinsRef.current.forEach((p) => (p.map = null))
    pinsRef.current = []
    lineRef.current?.setMap(null)
    lineRef.current = null
    activityPoints.forEach((a) => {
      pinsRef.current.push(new markerLib.AdvancedMarkerElement({ map, position: { lat: a.lat, lng: a.lon }, content: pinContent(a.label, '#d97706'), zIndex: 8800 }))
    })
    if (!work) return
    pinsRef.current.push(new markerLib.AdvancedMarkerElement({ map, position: work, content: pinContent('Work', '#7c3aed'), zIndex: 8900 }))
    if (origin) {
      lineRef.current = new google.maps.Polyline({
        map,
        path: [origin, work],
        strokeOpacity: 0,
        icons: [{ icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.6, strokeColor: '#7c3aed', scale: 3 }, offset: '0', repeat: '14px' }],
        clickable: false,
      })
    }
  }, [map, markerLib, origin, work, activityPoints])
  return null
}

function HomeAndRadius() {
  const map = useMap()
  const markerLib = useMapsLibrary('marker')
  const { origin, filters, fitRequest, recommendation, selected, work } = useStore()
  const circleRef = useRef<google.maps.Circle | null>(null)
  const homeRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null)
  // Read at call time so inset changes alone never re-run the fit/pan effects.
  const currentInset = () => useStore.getState().mapInsetBottom
  const mapInsetBottom = useStore((s) => s.mapInsetBottom)
  const initialPanDone = useRef(false)

  // On first load under a bottom sheet, nudge the default view so the county (not the
  // area north of it) sits in the uncovered part of the map. Later fits take precedence.
  useEffect(() => {
    if (!map || initialPanDone.current || mapInsetBottom === 0 || origin || recommendation) return
    initialPanDone.current = true
    map.panBy(0, usableInset(map, mapInsetBottom) / 2)
  }, [map, mapInsetBottom, origin, recommendation])

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
        fillColor: BRAND_BLUE,
        fillOpacity: 0.06,
        strokeColor: BRAND_BLUE,
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
    const picks = recommendation?.results.slice(0, 5) ?? []
    if (picks.length) {
      picks.forEach((s) => {
        b.extend({ lat: s.lat, lng: s.lon })
        n++
      })
      if (origin) b.extend(origin)
      if (work) b.extend(work)
    } else if (origin) {
      const r = (filters.radius ?? 3) * 1609.34
      const c = new google.maps.Circle({ center: origin, radius: r })
      const cb = c.getBounds()
      if (cb) {
        b.union(cb)
        n++
      }
    }
    if (n > 0) {
      const pad = 60
      map.fitBounds(b, { top: pad, left: pad, right: pad, bottom: pad + usableInset(map, currentInset()) })
    }
  }, [map, fitRequest, recommendation, origin, work, filters.radius])

  useEffect(() => {
    if (!map || !selected) return
    const p = { lat: selected.lat, lng: selected.lon }
    const inset = usableInset(map, currentInset())
    const bounds = map.getBounds()
    if (!bounds) {
      map.panTo(p)
      return
    }
    if (inset === 0) {
      if (!bounds.contains(p)) map.panTo(p)
      return
    }
    // A sheet covers the bottom of the map: the pin must land in the uncovered strip.
    const proj = map.getProjection()
    const zoom = map.getZoom()
    const mapH = map.getDiv().clientHeight
    const pt = proj?.fromLatLngToPoint(p)
    const top = proj?.fromLatLngToPoint(bounds.getNorthEast())
    if (!proj || zoom == null || !pt || !top || !mapH) {
      if (!bounds.contains(p)) map.panTo(p)
      return
    }
    const scale = 2 ** zoom
    const yPx = (pt.y - top.y) * scale
    const visible = bounds.contains(p) && yPx > 40 && yPx < mapH - inset - 40
    if (visible) return
    // Centre the pin in the visible strip: shift the map centre south by half the inset.
    const target = proj.fromPointToLatLng(new google.maps.Point(pt.x, pt.y + inset / 2 / scale))
    if (target) map.panTo(target)
  }, [map, selected])

  return null
}

function GoogleMapView({ mapId }: { mapId: string }) {
  const isDesktop = useIsDesktop()
  const mapBounds = useStore((s) => s.config?.map_bounds)
  const restriction = useMemo(
    () => (mapBounds ? { latLngBounds: mapBounds, strictBounds: true } : undefined),
    [mapBounds],
  )
  return (
    <Map
      defaultCenter={MIAMI}
      defaultZoom={10}
      restriction={restriction}
      mapId={mapId}
      gestureHandling="greedy"
      disableDefaultUI
      zoomControl={isDesktop}
      clickableIcons={false}
      className="h-full w-full"
      onClick={() => void useStore.getState().select(null)}
    >
      <Markers />
      <HomeAndRadius />
      <HouseholdPins />
    </Map>
  )
}

// ----------------------------------------------------------------------------------
// Fallback: a simple projected plot used only when no Google Maps key is configured.
// ----------------------------------------------------------------------------------
const FB_FALLBACK = { south: 25.3, west: -80.65, north: 26.0, east: -80.08 }

function FallbackMap() {
  const { schools, recommendation, selectedId, hoverId, select, setHover, origin, filters, work, mode } = useStore()
  const FB = useStore((s) => s.config?.map_bounds) ?? FB_FALLBACK
  const W = 1000
  const H = Math.round((W * (FB.north - FB.south)) / ((FB.east - FB.west) * Math.cos((25.7 * Math.PI) / 180)))
  const px = (lon: number) => ((lon - FB.west) / (FB.east - FB.west)) * W
  const py = (lat: number) => ((FB.north - lat) / (FB.north - FB.south)) * H
  const picks = (recommendation?.results ?? []).slice(0, 5)
  const ranked = new globalThis.Map<number, number>()
  picks.forEach((r, i) => ranked.set(r.id, i + 1))
  const mute = mode === 'match' && ranked.size > 0
  const radiusPx = origin && filters.radius ? (filters.radius / 69) * (H / (FB.north - FB.south)) : 0
  // Zoom the viewBox to the visible points (plus home/radius) with padding.
  const focus = picks.length ? picks : schools
  let vb = `0 0 ${W} ${H}`
  if (focus.length) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    const ext = (x: number, y: number, r = 0) => { x0 = Math.min(x0, x - r); y0 = Math.min(y0, y - r); x1 = Math.max(x1, x + r); y1 = Math.max(y1, y + r) }
    focus.forEach((s) => ext(px(s.lon), py(s.lat)))
    if (origin) ext(px(origin.lng), py(origin.lat), radiusPx)
    if (work) ext(px(work.lng), py(work.lat))
    const pad = Math.max(20, (x1 - x0) * 0.15, (y1 - y0) * 0.15)
    let vx = x0 - pad
    let vy = y0 - pad
    let vw = Math.max(80, x1 - x0 + pad * 2)
    let vh = Math.max(80, y1 - y0 + pad * 2)
    vx = Math.max(0, Math.min(vx, W - 80))
    vy = Math.max(0, Math.min(vy, H - 80))
    vw = Math.min(vw, W - vx)
    vh = Math.min(vh, H - vy)
    vb = `${vx} ${vy} ${vw} ${vh}`
  }
  return (
    <div className="relative h-full w-full bg-[#e8eef5]">
      <svg viewBox={vb} className="h-full w-full" preserveAspectRatio="xMidYMid meet" onClick={() => void select(null)}>
        <rect width={W} height={H} fill="#e8eef5" />
        {origin && radiusPx > 0 && <circle cx={px(origin.lng)} cy={py(origin.lat)} r={radiusPx} fill={BRAND_BLUE} fillOpacity={0.07} stroke={BRAND_BLUE} strokeOpacity={0.5} strokeWidth={1.5} />}
        {schools.map((s) => {
          const r = ranked.get(s.id)
          const selected = s.id === selectedId
          const hovered = s.id === hoverId && !selected
          const faded = mute && !r && !selected && !hovered
          const baseR = r ? 9 : faded ? 4 : 6
          const baseStroke = r ? 2 : 0.8
          const extra = selected ? 5 : hovered ? 1.6 : 0
          return (
            <g key={s.id} onClick={(e) => { e.stopPropagation(); void select(s.id) }} onMouseEnter={() => setHover(s.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              <circle cx={px(s.lon)} cy={py(s.lat)} r={baseR + extra / 2} fill={CATEGORY_META[s.category].color} stroke="white" strokeWidth={baseStroke + extra} opacity={r || selected || hovered ? 1 : faded ? 0.35 : 0.8} />
              {r && (
                <text x={px(s.lon)} y={py(s.lat) + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
                  {r}
                </text>
              )}
              <title>{s.name}</title>
            </g>
          )
        })}
        {picks.filter((s) => !schools.some((x) => x.id === s.id)).map((s) => {
          const r = ranked.get(s.id)
          const selected = s.id === selectedId
          const hovered = s.id === hoverId && !selected
          const extra = selected ? 5 : hovered ? 1.6 : 0
          return (
            <g key={`pin-${s.id}`} onClick={(e) => { e.stopPropagation(); void select(s.id) }} onMouseEnter={() => setHover(s.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              <circle cx={px(s.lon)} cy={py(s.lat)} r={9 + extra / 2} fill={CATEGORY_META[s.category].color} stroke="white" strokeWidth={2 + extra} />
              <text x={px(s.lon)} y={py(s.lat) + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
                {r}
              </text>
              <title>{s.name}</title>
            </g>
          )
        })}
        {origin && work && <line x1={px(origin.lng)} y1={py(origin.lat)} x2={px(work.lng)} y2={py(work.lat)} stroke="#7c3aed" strokeOpacity={0.6} strokeWidth={1.5} strokeDasharray="4 4" />}
        {origin && (
          <g>
            <circle cx={px(origin.lng)} cy={py(origin.lat)} r={7} fill="#0f172a" stroke="white" strokeWidth={2.5} />
          </g>
        )}
        {work && (
          <g>
            <circle cx={px(work.lng)} cy={py(work.lat)} r={7} fill="#7c3aed" stroke="white" strokeWidth={2.5} />
            <title>Work</title>
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
  if (config.maps_browser_key) return <GoogleMapView mapId={config.map_id ?? 'DEMO_MAP_ID'} />
  return <FallbackMap />
}
