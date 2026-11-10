import type { Monitor, Segment, SliceTimes } from '../../core/types';

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
    .join(', ');
}
const CLOCK = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
/** Recorded clock times for the flights last priced, or none when they do not fit the trip. */
export function flightTimes(monitor: Monitor): SliceTimes[] {
  const schedule = monitor.latest?.schedule;
  const segments = monitor.latest?.observed_offer?.segments ?? monitor.target.segments;
  if (!Array.isArray(schedule) || !schedule.length || schedule.length !== segments.length)
    return [];
  return schedule.every((item) => CLOCK.test(item?.departs) && CLOCK.test(item?.arrives))
    ? schedule
    : [];
}
export function travelTime(minutes: number | null | undefined): string {
  if (!Number.isInteger(minutes) || !minutes || minutes < 0 || minutes > 1440) return '';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return [hours ? `${hours} hr` : '', rest ? `${rest} min` : ''].filter(Boolean).join(' ');
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
