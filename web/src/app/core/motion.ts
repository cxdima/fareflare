/** True when the visitor has not asked their device for less motion. */
export function allowsMotion(): boolean {
  return (
    typeof matchMedia === 'function' && !matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** How far a tall element has been scrolled through while it fills the window, from 0 to 1. */
export function scrolledThrough(track: HTMLElement): number {
  const box = track.getBoundingClientRect();
  const distance = box.height - innerHeight;
  return distance > 0 ? Math.min(1, Math.max(0, -box.top / distance)) : 0;
}
