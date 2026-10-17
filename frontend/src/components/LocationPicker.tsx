import { useMapsLibrary } from '@vis.gl/react-google-maps'
import { LocateFixed, MapPin, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useStore } from '../store'

function geolocationMessage(err: GeolocationPositionError): string {
  switch (err.code) {
    case err.PERMISSION_DENIED:
      return 'Location permission was denied. You can enter an address instead.'
    case err.POSITION_UNAVAILABLE:
      return 'Your location is unavailable right now. Try an address or ZIP instead.'
    case err.TIMEOUT:
      return 'Finding your location timed out. Try again or enter an address.'
    default:
      return 'Could not get your location. You can enter an address instead.'
  }
}

function RememberLocation() {
  const origin = useStore((s) => s.origin)
  const rememberLocation = useStore((s) => s.rememberLocation)
  const setRememberLocation = useStore((s) => s.setRememberLocation)
  if (!origin) return null
  return (
    <label className="flex items-start gap-2 text-xs text-slate-600">
      <input
        type="checkbox"
        className="mt-0.5"
        checked={rememberLocation}
        onChange={(e) => void setRememberLocation(e.target.checked)}
      />
      <span>Remember this location for my match chat</span>
    </label>
  )
}

function LocationShell({
  onSubmit,
  locating,
  status,
  onUseMyLocation,
  children,
}: {
  onSubmit: (e: FormEvent) => void
  locating: boolean
  status: string | null
  onUseMyLocation: () => void
  children: ReactNode
}) {
  const locateError = useStore((s) => s.locateError)
  return (
    <div className="relative z-30 space-y-2">
      <form onSubmit={onSubmit} className="flex gap-2">
        {children}
        <button type="submit" disabled={locating} className="rounded-xl bg-brand-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-brand-700 disabled:opacity-60">
          {locating ? '…' : 'Go'}
        </button>
        <button type="button" onClick={onUseMyLocation} disabled={locating} title="Use my current location" className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 shadow-sm hover:bg-slate-50 disabled:opacity-60">
          <LocateFixed className={`size-4 ${locating ? 'animate-pulse' : ''}`} />
        </button>
      </form>
      {status && <div className="text-xs text-slate-500">{status}</div>}
      {locateError && <div className="text-xs text-rose-600">{locateError}</div>}
      <RememberLocation />
    </div>
  )
}

function getPosition(options: PositionOptions): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(resolve, reject, options)
  })
}

async function geolocationPermission(): Promise<PermissionState | 'unknown'> {
  try {
    if (!navigator.permissions?.query) return 'unknown'
    const status = await navigator.permissions.query({ name: 'geolocation' })
    return status.state
  } catch {
    return 'unknown'
  }
}

async function readCurrentPosition(): Promise<GeolocationPosition> {
  const permission = await geolocationPermission()
  // The permission prompt counts against timeout. Give a first allow plenty of time,
  // and ask macOS/CoreLocation directly — a short coarse-network lookup times out here.
  if (permission !== 'granted') {
    return getPosition({ enableHighAccuracy: true, maximumAge: 60_000, timeout: 45_000 })
  }
  try {
    return await getPosition({ enableHighAccuracy: false, maximumAge: 5 * 60_000, timeout: 4_000 })
  } catch (err) {
    if ((err as GeolocationPositionError).code === 1) throw err
    return getPosition({ enableHighAccuracy: true, maximumAge: 0, timeout: 25_000 })
  }
}

async function requestCurrentLocation(setLocating: (v: boolean) => void, setStatus: (v: string | null) => void) {
  const { setOrigin, setLocateError } = useStore.getState()
  if (!navigator.geolocation) {
    setLocateError('This browser cannot share your location. Enter an address instead.')
    return
  }
  setLocateError(null)
  setStatus('Finding your location…')
  setLocating(true)
  try {
    const position = await readCurrentPosition()
    setOrigin({ lat: position.coords.latitude, lng: position.coords.longitude, label: 'Current location' })
    setStatus(null)
  } catch (err) {
    setStatus(null)
    const geo = err as GeolocationPositionError
    setLocateError(typeof geo.code === 'number' ? geolocationMessage(geo) : 'Could not get your location. You can enter an address instead.')
  } finally {
    setLocating(false)
  }
}

function TextLocationPicker() {
  const origin = useStore((s) => s.origin)
  const setOrigin = useStore((s) => s.setOrigin)
  const locate = useStore((s) => s.locate)
  const [loc, setLoc] = useState('')
  const [locating, setLocating] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    setLoc(origin?.label ?? '')
  }, [origin])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const q = loc.trim()
    if (!q) {
      setOrigin(null)
      return
    }
    setLocating(true)
    await locate(q)
    setLocating(false)
  }

  return (
    <LocationShell onSubmit={onSubmit} locating={locating} status={status} onUseMyLocation={() => void requestCurrentLocation(setLocating, setStatus)}>
      <div className="relative min-w-0 flex-1">
        <MapPin className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          value={loc}
          onChange={(e) => {
            const next = e.target.value
            setLoc(next)
            if (!next.trim()) setOrigin(null)
          }}
          placeholder="Home address, neighborhood, or ZIP"
          className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-9 text-base shadow-sm outline-none ring-accent/40 placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 md:text-sm"
        />
        {origin && (
          <button type="button" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }} onClick={() => setOrigin(null)} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Clear location">
            <X className="size-4" />
          </button>
        )}
      </div>
    </LocationShell>
  )
}

function PlacesLocationPicker() {
  const places = useMapsLibrary('places')
  const origin = useStore((s) => s.origin)
  const setOrigin = useStore((s) => s.setOrigin)
  const bounds = useStore((s) => s.config?.bounds)
  const hostRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<google.maps.places.PlaceAutocompleteElement | null>(null)
  const [locating, setLocating] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!places || !hostRef.current) return
    const el = new places.PlaceAutocompleteElement({
      includedRegionCodes: ['us'],
      requestedRegion: 'us',
      locationBias: bounds ?? null,
      placeholder: 'Home address, neighborhood, or ZIP',
    })
    el.noClearButton = true
    el.classList.add('location-autocomplete')
    let picked = false
    const onSelect = (ev: Event) => {
      picked = true
      window.setTimeout(() => {
        picked = false
      }, 400)
      void applyPlace(ev as google.maps.places.PlacePredictionSelectEvent)
    }
    const onEnter = (ev: Event) => {
      const key = ev as KeyboardEvent
      if (key.key !== 'Enter' || key.isComposing) return
      key.preventDefault()
      window.setTimeout(() => {
        if (picked) return
        const q = el.value.trim()
        if (!q) {
          useStore.getState().setOrigin(null)
          return
        }
        setLocating(true)
        void useStore.getState().locate(q).finally(() => setLocating(false))
      }, 250)
    }
    const onInput = (ev: Event) => {
      if (!ev.isTrusted || el.value.trim()) return
      useStore.getState().setOrigin(null)
    }
    el.addEventListener('gmp-select', onSelect)
    el.addEventListener('keydown', onEnter)
    el.addEventListener('input', onInput)
    hostRef.current.replaceChildren(el)
    widgetRef.current = el
    if (useStore.getState().origin) el.value = useStore.getState().origin?.label ?? ''
    setReady(true)
    return () => {
      el.removeEventListener('gmp-select', onSelect)
      el.removeEventListener('keydown', onEnter)
      el.removeEventListener('input', onInput)
      el.remove()
      widgetRef.current = null
      setReady(false)
    }
  }, [places, bounds])

  useEffect(() => {
    const el = widgetRef.current
    if (!el) return
    const next = origin?.label ?? ''
    if (el.value !== next) el.value = next
  }, [origin])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const q = widgetRef.current?.value.trim() ?? ''
    if (!q) {
      setOrigin(null)
      return
    }
    setLocating(true)
    await useStore.getState().locate(q)
    setLocating(false)
  }

  if (!places) return <TextLocationPicker />

  return (
    <LocationShell onSubmit={onSubmit} locating={locating} status={status} onUseMyLocation={() => void requestCurrentLocation(setLocating, setStatus)}>
      <div className="relative min-w-0 flex-1">
        <div ref={hostRef} className={ready ? '' : 'hidden'} />
        {!ready && <div className="h-10 animate-pulse rounded-xl bg-slate-100" />}
        {origin && (
          <button type="button" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }} onClick={() => setOrigin(null)} className="absolute right-2 top-1/2 z-10 -translate-y-1/2 rounded-md bg-white p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Clear location">
            <X className="size-4" />
          </button>
        )}
      </div>
    </LocationShell>
  )
}

async function applyPlace(ev: google.maps.places.PlacePredictionSelectEvent) {
  const { setOrigin, setLocateError } = useStore.getState()
  try {
    const place = ev.placePrediction.toPlace()
    await place.fetchFields({ fields: ['location', 'formattedAddress', 'displayName'] })
    const loc = place.location
    if (!loc) {
      setLocateError('Could not locate that place in Miami-Dade County')
      return
    }
    const label = place.formattedAddress || place.displayName || ev.placePrediction.text.toString()
    setOrigin({ lat: loc.lat(), lng: loc.lng(), label })
  } catch {
    setLocateError('Could not locate that place in Miami-Dade County')
  }
}

export function LocationPicker() {
  const mapsKey = useStore((s) => s.config?.maps_browser_key)
  if (mapsKey) return <PlacesLocationPicker />
  return <TextLocationPicker />
}
