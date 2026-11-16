export interface HoverViewport {
  left: number
  top: number
  width: number
  height: number
  layoutHeight: number
}

/** Reserve actual visible space; a short viewport must not inherit a larger minimum. */
export function gameHoverPlacement(point: { x: number; y: number }, viewport: HoverViewport, anchor?: { left: number; right: number; top: number; bottom: number }) {
  const gap = 8
  const right = viewport.left + viewport.width
  const bottom = viewport.top + viewport.height
  const width = Math.max(1, Math.min(384, viewport.width - gap * 2))
  const y = Math.max(viewport.top + gap, Math.min(point.y, bottom - gap))
  const fitsRight = anchor && anchor.right + width + 12 <= right - gap
  const fitsLeft = anchor && anchor.left - width - 12 >= viewport.left + gap
  const beside = fitsRight || fitsLeft
  const minimum = Math.min(320, viewport.height - gap * 2)
  const sideTop = Math.max(viewport.top + gap, Math.min(anchor?.top ?? y, bottom - gap - minimum))
  const oversized = anchor && Math.max(bottom - anchor.bottom - 20, anchor.top - viewport.top - 20) < Math.min(120, viewport.height / 3)
  const belowEdge = oversized ? y : anchor?.bottom ?? y
  const aboveEdge = oversized ? y : anchor?.top ?? y
  const belowTop = beside ? sideTop : Math.min(bottom - gap - 1, Math.max(viewport.top + gap, belowEdge + 12))
  const aboveBottom = Math.max(viewport.top + gap, Math.min(bottom - gap, aboveEdge - 12))
  const below = Math.max(1, bottom - gap - belowTop)
  const above = Math.max(1, aboveBottom - viewport.top - gap)
  const upwards = !beside && below < 300 && above > below
  const requestedLeft = fitsRight ? anchor!.right + 12 : fitsLeft ? anchor!.left - width - 12 : anchor?.left ?? point.x + 20
  return {
    left: `${Math.max(viewport.left + gap, Math.min(requestedLeft, right - width - gap))}px`,
    width: `${width}px`,
    maxWidth: `${Math.max(1, viewport.width - gap * 2)}px`,
    maxHeight: `${upwards ? above : below}px`,
    top: upwards ? 'auto' : `${belowTop}px`,
    bottom: upwards ? `${viewport.layoutHeight - aboveBottom}px` : 'auto',
  }
}
