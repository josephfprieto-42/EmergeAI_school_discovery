import { useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
    () => true,
  )
}

/** Tailwind `md` breakpoint. Below this the app uses the map-first bottom-sheet layout. */
export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 768px)')
}

/** Coarse pointer = touch device (no hover, on-screen keyboard). */
export function useIsTouch(): boolean {
  return useMediaQuery('(pointer: coarse)')
}
