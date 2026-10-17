import { MarkerClusterer, SuperClusterAlgorithm } from '@googlemaps/markerclusterer'
import { Map, useMap, useMapsLibrary } from '@vis.gl/react-google-maps'
import { useEffect, useMemo, useRef } from 'react'
import { useIsDesktop } from '../hooks/useMediaQuery'
import { CATEGORY_META } from '../lib/format'
import { useStore } from '../store'
import type { School } from '../types'

const MIAMI = { lat: 25.76, lng: -80.3 }
const BRAND_BLUE = CATEGORY_META.public.color
/** Far enough to split a cluster into pins, short of a rooftop dive. */
const CLUSTER_ZOOM_CAP = 16

let clusterCameraToken = 0

/** Zoom at which `bounds` fills the viewport, matching what fitBounds aims for. */
function zoomToFit(map: google.maps.Map, bounds: google.maps.LatLngBounds): number {
  const ne = bounds.getNorthEast()
  const sw = bounds.getSouthWest()
  const midLat = (ne.lat() + sw.lat()) / 2
  const latMeters = Math.abs(ne.lat() - sw.lat()) * 111320
  const lngMeters = Math.abs(ne.lng() - sw.lng()) * 111320 * Math.cos((midLat * Math.PI) / 180)
  const div = map.getDiv()
  const width = Math.max(div.clientWidth * 0.72, 160)
  const height = Math.max(div.clientHeight * 0.72, 160)
  const mpp0 = 156543.03392 * Math.cos((midLat * Math.PI) / 180)
  const zoomFor = (meters: number, px: number) => (meters < 30 ? CLUSTER_ZOOM_CAP : Math.log2((px * mpp0) / meters))
  return Math.min(CLUSTER_ZOOM_CAP, zoomFor(lngMeters, width), zoomFor(latMeters, height))
}

function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

/**
 * fitBounds only animates a small zoom change, so a tight cluster snaps.
 * Pan onto the cluster first, then zoom, so it stays in the middle instead of
 * sliding away while the zoom pulls toward the old center.
 */
function animateToBounds(map: google.maps.Map, bounds: google.maps.LatLngBounds) {
  const startZoom = map.getZoom()
  const startCenter = map.getCenter()
  const center = bounds.getCenter()
  if (startZoom == null || !startCenter) {
    map.fitBounds(bounds)
    return
  }
  const targetZoom = Math.max(startZoom, zoomToFit(map, bounds))
  const target = { lat: center.lat(), lng: center.lng() }
  const start = { lat: startCenter.lat(), lng: startCenter.lng() }
  const levels = Math.abs(targetZoom - startZoom)
  const moved = Math.abs(start.lat - target.lat) > 1e-5 || Math.abs(start.lng - target.lng) > 1e-5
  if (levels < 0.05 && !moved) return
  const duration = Math.min(3200, Math.max(900, levels * 340))
  const token = ++clusterCameraToken
  let t0 = 0
  let cleaned = false
  const div = map.getDiv()
  const cleanup = () => {
    if (cleaned) return
    cleaned = true
    drag.remove()
    div.removeEventListener('wheel', cancel)
  }
  const cancel = () => {
    if (clusterCameraToken !== token) return
    clusterCameraToken += 1
    cleanup()
  }
  const drag = map.addListener('dragstart', cancel)
  div.addEventListener('wheel', cancel, { passive: true })
  const step = (now: number) => {
    if (token !== clusterCameraToken) {
      cleanup()
      return
    }
    if (!t0) t0 = now
    const t = Math.min(1, (now - t0) / duration)
    // Pan while the zoom stays put, then zoom with the cluster already centered.
    const panShare = moved && levels >= 0.05 ? 0.45 : moved ? 1 : 0
    let lat = target.lat
    let lng = target.lng
    let zoom = targetZoom
    if (t < panShare) {
      const u = easeInOut(t / panShare)
      lat = start.lat + (target.lat - start.lat) * u
      lng = start.lng + (target.lng - start.lng) * u
      zoom = startZoom
    } else {
      const u = easeInOut(panShare >= 1 ? 1 : (t - panShare) / (1 - panShare))
      zoom = startZoom + (targetZoom - startZoom) * u
    }
    map.moveCamera({ center: { lat, lng }, zoom })
    if (t < 1) requestAnimationFrame(step)
    else cleanup()
  }
  requestAnimationFrame(step)
}

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

function markerContent(s: School, rank: number | null, state: 'normal' | 'selected' | 'hover'): HTMLElement {
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
    el.innerHTML = `<div style="padding:${ring}px;border-radius:9999px;background:white;box-shadow:0 1px 3px rgba(0,0,0,.4);line-height:0"><div style="width:14px;height:14px;border-radius:9999px;background:${color}"></div></div>`
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
  // Once a match exists, the map shows only that result set.
  const matchOnly = mode === 'match' && rankById.size > 0

  // Clustered markers for schools outside the match set. Hidden during an active match.
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    clustererRef.current?.clearMarkers()
    markersRef.current.clear()
    const markers: google.maps.marker.AdvancedMarkerElement[] = []
    if (!matchOnly) {
      for (const s of schools) {
        const m = new AdvancedMarkerElement({
          position: { lat: s.lat, lng: s.lon },
          content: markerContent(s, null, 'normal'),
          anchorLeft: '-50%',
          anchorTop: '-50%',
        })
        m.addListener('click', () => void select(s.id))
        bindMarkerHover(m.content as HTMLElement, s.id, setHover)
        markersRef.current.set(s.id, m)
        markers.push(m)
      }
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
    clustererRef.current.onClusterClick = (_event, cluster, clusterMap) => {
      if (cluster.bounds) animateToBounds(clusterMap, cluster.bounds)
    }
    clustererRef.current.addMarkers(markers)
    return () => {
      clustererRef.current?.clearMarkers()
    }
  }, [map, markerLib, schools, select, setHover, matchOnly])

  // Numbered pins for recommendation results. Explore uses the regular markers instead.
  useEffect(() => {
    if (!map || !markerLib) return
    const { AdvancedMarkerElement } = markerLib
    pinnedRef.current.forEach((m) => (m.map = null))
    pinnedRef.current = []
    pinnedByIdRef.current.clear()
    if (!matchOnly) return
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
  }, [map, markerLib, picks, rankById, select, matchOnly])

  // Selected / hover styling. The colored dot stays the same size; only the white ring grows.
  useEffect(() => {
    const ids = [...new Set([selectedId, hoverId].filter((x): x is number => x != null))]
    const touched: { marker: google.maps.marker.AdvancedMarkerElement; id: number; rank: number | null }[] = []
    for (const id of ids) {
      const state = id === selectedId ? 'selected' : 'hover'
      const clustered = markersRef.current.get(id)
      const school = schools.find((x) => x.id === id)
      if (clustered && school) {
        clustered.content = markerContent(school, null, state)
        bindMarkerHover(clustered.content as HTMLElement, id, setHover)
        clustered.zIndex = 4000
        touched.push({ marker: clustered, id, rank: null })
      }
      const pinned = pinnedByIdRef.current.get(id)
      const pick = picks.find((x) => x.id === id)
      if (matchOnly && pinned && pick) {
        const rank = rankById.get(id) ?? null
        pinned.content = markerContent(pick, rank, state)
        pinned.zIndex = 4000
        touched.push({ marker: pinned, id, rank })
      }
    }
    return () => {
      for (const t of touched) {
        const school = (t.rank != null ? picks : schools).find((x) => x.id === t.id)
        if (!school) continue
        t.marker.content = markerContent(school, t.rank, 'normal')
        if (t.rank == null) bindMarkerHover(t.marker.content as HTMLElement, t.id, setHover)
        t.marker.zIndex = t.rank != null ? 5000 : null
      }
    }
  }, [selectedId, hoverId, schools, picks, rankById, setHover, matchOnly])

  return null
}

/** Rough lat/lng box around a point. Avoids a map Circle, which would stay visible after clear. */
function boundsAround(center: google.maps.LatLngLiteral, radiusMeters: number): google.maps.LatLngBounds {
  const latRad = (center.lat * Math.PI) / 180
  const dLat = radiusMeters / 111320
  const dLng = radiusMeters / (111320 * Math.cos(latRad) || 1)
  const b = new google.maps.LatLngBounds()
  b.extend({ lat: center.lat + dLat, lng: center.lng + dLng })
  b.extend({ lat: center.lat - dLat, lng: center.lng - dLng })
  return b
}

/** Bottom-sheet inset, capped so padding never exceeds the visible map. */
function usableInset(map: google.maps.Map, inset: number): number {
  const h = map.getDiv().clientHeight || 0
  return Math.max(0, Math.min(inset, Math.round(h * 0.55)))
}

/**
 * Where the open map's center sits, relative to the canvas center (+x right, +y down).
 * A top card shifts it down; a full-height side panel shifts it sideways.
 */
function openCenterDelta(map: google.maps.Map): { x: number; y: number } {
  const mapRect = map.getDiv().getBoundingClientRect()
  if (mapRect.width < 40 || mapRect.height < 40) return { x: 0, y: 0 }
  const cx = mapRect.left + mapRect.width / 2
  const cy = mapRect.top + mapRect.height / 2
  let left = mapRect.left
  let right = mapRect.right
  let top = mapRect.top
  let bottom = mapRect.bottom
  const main = map.getDiv().closest('main')
  if (main) {
    for (const el of main.querySelectorAll(':scope > *')) {
      if (!(el instanceof HTMLElement) || el.contains(map.getDiv())) continue
      const r = el.getBoundingClientRect()
      const overlapW = Math.min(r.right, mapRect.right) - Math.max(r.left, mapRect.left)
      const overlapH = Math.min(r.bottom, mapRect.bottom) - Math.max(r.top, mapRect.top)
      if (overlapW < 48 || overlapH < 48) continue
      const flush = (a: number, b: number) => Math.abs(a - b) < 28
      const side = overlapH > mapRect.height * 0.75
      const bar = overlapW > mapRect.width * 0.5
      if (side && flush(r.left, mapRect.left)) left = Math.max(left, r.right)
      else if (side && flush(r.right, mapRect.right)) right = Math.min(right, r.left)
      else if (bar && flush(r.top, mapRect.top)) top = Math.max(top, r.bottom)
      else if (bar && flush(r.bottom, mapRect.bottom)) bottom = Math.min(bottom, r.top)
    }
  }
  const inset = usableInset(map, useStore.getState().mapInsetBottom)
  if (inset > 0) bottom = Math.min(bottom, mapRect.bottom - inset)
  if (right - left < 80 || bottom - top < 80) return { x: 0, y: 0 }
  return { x: (left + right) / 2 - cx, y: (top + bottom) / 2 - cy }
}

function pinContent(label: string, dotColor: string): HTMLElement {
  const el = document.createElement('div')
  el.innerHTML = `<div style="display:flex;align-items:center;gap:6px;background:white;border-radius:9999px;padding:4px 10px 4px 6px;box-shadow:0 2px 10px rgba(0,0,0,.25);font:600 12px Inter,system-ui,sans-serif;color:#0f172a"><span style="width:14px;height:14px;border-radius:9999px;background:${dotColor};border:3px solid white;box-shadow:0 0 0 2px ${dotColor}"></span>${label}</div>`
  return el
}

/** Small house glyph. Clicks pass through so nearby school pins stay selectable. */
function homeMarkerContent(): HTMLElement {
  const el = document.createElement('div')
  el.title = 'Home'
  el.style.pointerEvents = 'none'
  el.style.lineHeight = '0'
  el.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" style="display:block;overflow:visible;filter:drop-shadow(0 1px 2px rgba(15,23,42,.45))"><path d="M4 11.2 12 4.5l8 6.7V20a1 1 0 0 1-1 1h-5.2v-6.2H10.2V21H5a1 1 0 0 1-1-1Z" fill="#0f172a" stroke="white" stroke-width="2.25" stroke-linejoin="round"/></svg>`
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
  const { origin, filters, fitRequest, recommendation, selected, selectedId, schools, work, mode, viewReset } = useStore()
  const hadSelection = useRef(selectedId != null)
  const seenFitReset = useRef(viewReset)
  const seenSelectionReset = useRef(viewReset)
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
    const detach = () => {
      const marker = homeRef.current
      homeRef.current = null
      if (marker) {
        marker.map = null
        marker.remove()
      }
      const circle = circleRef.current
      circleRef.current = null
      circle?.setMap(null)
    }
    // Drop the pin and radius as soon as the location is cleared, even if the
    // marker library is not ready on this render.
    if (!origin) {
      detach()
      return
    }
    if (!map || !markerLib) return
    detach()
    const marker = new markerLib.AdvancedMarkerElement({
      map,
      position: origin,
      content: homeMarkerContent(),
      title: 'Home',
      zIndex: 9000,
      gmpClickable: false,
      anchorLeft: '-50%',
      anchorTop: '-50%',
    })
    homeRef.current = marker
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
    return detach
  }, [map, markerLib, origin, filters.radius])

  useEffect(() => {
    if (!map || viewReset === 0) return
    map.setCenter(MIAMI)
    map.setZoom(10)
    const inset = currentInset()
    const { origin: home, recommendation: match } = useStore.getState()
    if (!home && !match && inset > 0) map.panBy(0, usableInset(map, inset) / 2)
  }, [map, viewReset])

  useEffect(() => {
    const resetting = seenFitReset.current !== viewReset
    seenFitReset.current = viewReset
    if (!map || fitRequest === 0 || resetting) return
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
      b.union(boundsAround(origin, (filters.radius ?? 3) * 1609.34))
      n++
    }
    if (!n) return
    const pad = 60
    const homeOnly = picks.length === 0 && !!origin
    map.fitBounds(b, { top: pad, left: pad, right: pad, bottom: pad + usableInset(map, currentInset()) })
    if (!homeOnly) return
    // fitBounds centres on the canvas, which sits under the search card. Slide so home
    // lands in the middle of the map that is still visible.
    const listener = google.maps.event.addListenerOnce(map, 'idle', () => {
      const d = openCenterDelta(map)
      if (Math.abs(d.x) < 8 && Math.abs(d.y) < 8) return
      map.panBy(-d.x, -d.y)
    })
    return () => google.maps.event.removeListener(listener)
  }, [map, fitRequest, recommendation, origin, work, filters.radius, viewReset])

  // Closing a school should put every loaded marker back in frame, not leave the map on that pin.
  useEffect(() => {
    if (!map) return
    const resetting = seenSelectionReset.current !== viewReset
    seenSelectionReset.current = viewReset
    const clearing = hadSelection.current && selectedId == null
    hadSelection.current = selectedId != null
    if (!clearing || resetting) return
    const b = new google.maps.LatLngBounds()
    let n = 0
    const picks = recommendation?.results.slice(0, 5) ?? []
    const matchOnly = mode === 'match' && picks.length > 0
    const pickIds = new Set(picks.map((s) => s.id))
    for (const s of schools) {
      if (matchOnly && !pickIds.has(s.id)) continue
      b.extend({ lat: s.lat, lng: s.lon })
      n++
    }
    for (const s of picks) {
      if (schools.some((x) => x.id === s.id)) continue
      b.extend({ lat: s.lat, lng: s.lon })
      n++
    }
    if (origin) {
      b.extend(origin)
      n++
    }
    if (work) {
      b.extend(work)
      n++
    }
    if (!n) return
    const pad = 48
    map.fitBounds(b, { top: pad, left: pad, right: pad, bottom: pad + usableInset(map, currentInset()) })
  }, [map, selectedId, schools, recommendation, origin, work, mode, viewReset])

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
  const matchOnly = mode === 'match' && ranked.size > 0
  const visibleSchools = matchOnly ? schools.filter((s) => ranked.has(s.id)) : schools
  const radiusPx = origin && filters.radius ? (filters.radius / 69) * (H / (FB.north - FB.south)) : 0
  // No selection frames every visible school. A selection frames that school.
  const selectedSchool = selectedId == null ? null : (visibleSchools.find((s) => s.id === selectedId) ?? picks.find((s) => s.id === selectedId) ?? null)
  const focus = selectedSchool ? [selectedSchool] : matchOnly ? picks : visibleSchools.length ? visibleSchools : picks
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
        {visibleSchools.map((s) => {
          const r = matchOnly ? ranked.get(s.id) : undefined
          const selected = s.id === selectedId
          const hovered = s.id === hoverId && !selected
          const baseR = r ? 9 : 6
          const baseStroke = r ? 2 : 0.8
          const extra = selected ? 5 : hovered ? 1.6 : 0
          return (
            <g key={s.id} onClick={(e) => { e.stopPropagation(); void select(s.id) }} onMouseEnter={() => setHover(s.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
              <circle cx={px(s.lon)} cy={py(s.lat)} r={baseR + extra / 2} fill={CATEGORY_META[s.category].color} stroke="white" strokeWidth={baseStroke + extra} opacity={r || selected || hovered ? 1 : 0.8} />
              {r && (
                <text x={px(s.lon)} y={py(s.lat) + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="white">
                  {r}
                </text>
              )}
              <title>{s.name}</title>
            </g>
          )
        })}
        {matchOnly && picks.filter((s) => !schools.some((x) => x.id === s.id)).map((s) => {
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
          <g transform={`translate(${px(origin.lng)} ${py(origin.lat)})`} pointerEvents="none">
            <title>Home</title>
            <path d="M-5.2 -1.2 0 -5.6 5.2 -1.2V5.2h-3.4V1.6H-1.8v3.6H-5.2Z" fill="#0f172a" stroke="white" strokeWidth={1.6} strokeLinejoin="round" />
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
