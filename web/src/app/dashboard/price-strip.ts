import type { Observation } from '../core/types';

export type StripBar = { x: number; y: number; height: number; kind: 'price' | 'low' | 'gap' };

/** The drawing is a fixed 16 places wide, so a young flight fills it from the right. */
export const STRIP = { slots: 16, step: 12, bar: 8, height: 44 } as const;

/**
 * Sorts recorded totals into equal spans of time, newest on the right. A span keeps the
 * lowest total recorded in it; a span with no record stays a gap and is never filled in.
 */
export function priceStrip(observations: readonly Observation[], interval: number) {
  const items = [...observations].sort((a, b) => a.observed_at - b.observed_at);
  if (!items.length) return null;
  const first = items[0];
  const latest = items[items.length - 1];
  const duration = latest.observed_at - first.observed_at;
  const span = Math.max(interval, 60, Math.ceil((duration + 1) / STRIP.slots));
  const count = Math.min(STRIP.slots, Math.floor(duration / span) + 1);
  const totals = new Array<number | null>(count).fill(null);
  for (const item of items) {
    const slot = Math.min(count - 1, Math.floor((item.observed_at - first.observed_at) / span));
    const held = totals[slot];
    totals[slot] = held === null ? item.amount_minor : Math.min(held, item.amount_minor);
  }
  const recorded = totals.filter((total): total is number => total !== null);
  const low = Math.min(...recorded);
  const high = Math.max(...recorded);
  const lowSlot = totals.lastIndexOf(low);
  const bars: StripBar[] = totals.map((total, slot) => {
    const share =
      total === null ? 0.34 : high === low ? 0.62 : 0.3 + (0.7 * (total - low)) / (high - low);
    const height = Math.round(STRIP.height * share * 10) / 10;
    return {
      x: (STRIP.slots - count + slot) * STRIP.step,
      y: STRIP.height - height,
      height,
      kind: total === null ? 'gap' : slot === lowSlot && high !== low ? 'low' : 'price',
    };
  });
  return { bars, first, latest, low, high, checks: items.length, gaps: count - recorded.length };
}
