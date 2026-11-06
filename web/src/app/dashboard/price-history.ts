import type { Observation } from '../core/types';
import { flightNumbers } from './shared/presentation';

export type HistoryRange = 'all' | '7' | '30';
export type HistoryPoint = { x: number; y: number; observation: Observation };

/** Derives comparisons and chart geometry from recorded totals, without interpolation. */
export function priceHistory(
  observations: readonly Observation[],
  range: HistoryRange,
  now: number,
  interval: number,
) {
  const cutoff = range === 'all' ? -Infinity : now - Number(range) * 86400;
  const items = observations
    .filter((item) => item.observed_at >= cutoff)
    .sort((a, b) => a.observed_at - b.observed_at);
  if (!items.length) return null;
  const first = items[0];
  const latest = items[items.length - 1];
  const low = Math.min(...items.map((item) => item.amount_minor));
  const high = Math.max(...items.map((item) => item.amount_minor));
  const duration = latest.observed_at - first.observed_at;
  const points = items.map((observation) => ({
    x: duration ? 8 + ((observation.observed_at - first.observed_at) / duration) * 624 : 320,
    y: high === low ? 90 : 164 - ((observation.amount_minor - low) / (high - low)) * 148,
    observation,
  }));
  const segments: HistoryPoint[][] = [];
  for (const point of points) {
    const segment = segments.at(-1);
    const previous = segment?.at(-1);
    if (
      !previous ||
      point.observation.observed_at - previous.observation.observed_at > interval * 2
    ) {
      segments.push([point]);
    } else {
      segment!.push(point);
    }
  }
  const change = latest.amount_minor - first.amount_minor;
  return {
    items,
    first,
    latest,
    low,
    high,
    change,
    percent: (Math.abs(change) / first.amount_minor) * 100,
    paths: segments.map((segment) => segment.map((point) => `${point.x},${point.y}`).join(' ')),
    endpoints: segments.flatMap((segment) =>
      segment.length === 1 ? segment : [segment[0], segment[segment.length - 1]],
    ),
    hasGaps: segments.length > 1,
  };
}

function csvCell(value: string | number): string {
  let text = String(value);
  // Quoting CSV syntax alone does not prevent spreadsheet formula execution.
  if (/^[\s\u0000-\u001f]*[=+@-]/u.test(text.normalize('NFKC')) || /^[\t\r\n]/.test(text)) {
    text = "'" + text;
  }
  return '"' + text.replaceAll('"', '""') + '"';
}

/** Locale-independent export of exactly the observations visible in the table. */
export function historyCsv(items: readonly Observation[]): string {
  const rows: (string | number)[][] = [
    [
      'observed_at_utc',
      'amount_minor',
      'currency',
      'price_basis',
      'fare',
      'matching_flights',
      'source',
    ],
    ...items.map((item) => [
      new Date(item.observed_at * 1000).toISOString(),
      item.amount_minor,
      item.currency,
      item.price_basis,
      item.fare_name ?? '',
      item.observed_offer ? flightNumbers(item.observed_offer.segments) : '',
      item.source,
    ]),
  ];
  return '\uFEFF' + rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n';
}
