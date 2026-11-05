import type { Monitor, Segment } from '../../core/types';

export function routeName(monitor: Monitor): string {
  const legs = monitor.target.segments[0]?.legs ?? [];
  return legs.length
    ? `${legs[0].origin} → ${legs[legs.length - 1].destination}`
    : 'Selected itinerary';
}
export function flightNumbers(segments: Segment[]): string {
  return segments
    .flatMap((segment) => segment.legs)
    .filter((leg) => leg.airline && leg.number)
    .map((leg) => `${leg.airline} ${leg.number}`)
    .join(' · ');
}
export function statusLabel(value: string): string {
  return (
    (
      {
        pending: 'Awaiting check',
        active: 'Watching',
        degraded: 'Check delayed',
        paused: 'Paused',
        cancelled: 'Stopped',
        expired: 'Departed',
        sent: 'Delivered',
        suppressed: 'Suppressed',
        dead_letter: 'Delivery failed',
        disabled: 'Disabled',
        deleted: 'Deleted',
        stale: 'Needs a fresh check',
      } as Record<string, string>
    )[value] ?? value
  );
}
export function reasonLabel(value: string): string {
  return (
    (
      {
        tracking_started: 'Tracking started',
        new_low: 'New observed low',
        below_price: 'Below your target',
        rebound: 'Price increased',
      } as Record<string, string>
    )[value] ?? value.replaceAll('_', ' ')
  );
}
