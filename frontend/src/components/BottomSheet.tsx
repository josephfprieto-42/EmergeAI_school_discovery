import clsx from 'clsx'
import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

export type SheetSnap = 'peek' | 'half' | 'full'

const ORDER: SheetSnap[] = ['peek', 'half', 'full']

/**
 * A bottom sheet that fills its (relatively positioned) parent and snaps between
 * three heights. Only the grab strip is draggable, so the content keeps native scrolling.
 */
export function BottomSheet({
  snap,
  onSnapChange,
  peekHeight = 128,
  header,
  children,
  zIndex = 20,
  onDismiss,
  onHeightChange,
  className,
  label,
}: {
  snap: SheetSnap
  onSnapChange: (s: SheetSnap) => void
  peekHeight?: number
  header?: ReactNode
  children: ReactNode
  zIndex?: number
  /** When set, dragging below the peek height closes the sheet. */
  onDismiss?: () => void
  /** Visible height in px, reported whenever the snap point or container changes. */
  onHeightChange?: (px: number) => void
  className?: string
  label?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [containerH, setContainerH] = useState(0)
  // Drag bookkeeping lives in a ref so pointer events never read a stale render.
  const dragRef = useRef<{ startY: number; startVisible: number; visible: number; moved: boolean } | null>(null)
  const [dragH, setDragH] = useState<number | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setContainerH(el.parentElement?.clientHeight ?? el.clientHeight)
    update()
    const ro = new ResizeObserver(update)
    if (el.parentElement) ro.observe(el.parentElement)
    return () => ro.disconnect()
  }, [])

  const heightFor = (s: SheetSnap) => (s === 'peek' ? Math.min(peekHeight, containerH) : s === 'half' ? Math.round(containerH * 0.5) : containerH)
  const targetH = heightFor(snap)
  const visibleH = dragH ?? targetH

  useEffect(() => {
    if (containerH > 0) onHeightChange?.(targetH)
  }, [targetH, containerH, onHeightChange])

  function onPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    if (e.button !== 0) return
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* pointer already released */
    }
    dragRef.current = { startY: e.clientY, startVisible: targetH, visible: targetH, moved: false }
    setDragH(targetH)
  }

  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    const d = dragRef.current
    if (!d) return
    const dy = e.clientY - d.startY
    const min = onDismiss ? 0 : heightFor('peek')
    d.visible = Math.max(min, Math.min(containerH, d.startVisible - dy))
    d.moved = d.moved || Math.abs(dy) > 6
    setDragH(d.visible)
  }

  function onPointerUp() {
    const d = dragRef.current
    if (!d) return
    const { visible, moved } = d
    dragRef.current = null
    setDragH(null)
    if (!moved) {
      // Tap on the grab strip cycles through the snap points.
      const next = ORDER[(ORDER.indexOf(snap) + 1) % ORDER.length]
      onSnapChange(next)
      return
    }
    if (onDismiss && visible < heightFor('peek') * 0.6) {
      onDismiss()
      return
    }
    let best: SheetSnap = 'peek'
    let bestDist = Infinity
    for (const s of ORDER) {
      const d = Math.abs(heightFor(s) - visible)
      if (d < bestDist) {
        best = s
        bestDist = d
      }
    }
    onSnapChange(best)
  }

  // The sheet is sized to its visible height (rather than translated) so the bottom of the
  // content, e.g. the chat composer or the last list item, is always reachable.
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={label}
      className={clsx('absolute inset-x-0 bottom-0 flex flex-col rounded-t-3xl border-t border-brand-100 bg-brand-50 shadow-[0_-8px_30px_rgba(15,23,42,0.18)]', className)}
      style={{
        zIndex,
        height: visibleH,
        transition: dragH != null ? 'none' : 'height 260ms cubic-bezier(.2,.8,.2,1)',
        visibility: containerH === 0 ? 'hidden' : undefined,
      }}
    >
      <div
        className="flex shrink-0 cursor-grab touch-none select-none items-center justify-center py-2.5 active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        aria-hidden
      >
        <span className="h-1.5 w-10 rounded-full bg-slate-300" />
      </div>
      {header && <div className="shrink-0 px-3 pb-2">{header}</div>}
      <div className="flex min-h-0 flex-1 flex-col overscroll-contain pb-[env(safe-area-inset-bottom)]">{children}</div>
    </div>
  )
}
