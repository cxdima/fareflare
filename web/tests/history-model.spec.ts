import { expect, test } from '@playwright/test';
import type { Observation } from '../src/app/core/types';
import { historyCsv, priceHistory } from '../src/app/dashboard/price-history';
import { monitor, observation } from './fixtures';

const day = 86400;
const instant = 1800000000;

function recorded(
  observedAt: number,
  amount: number,
  fields: Partial<Observation> = {},
): Observation {
  return {
    ...observation,
    price_basis: 'total',
    observed_at: observedAt,
    amount_minor: amount,
    ...fields,
  };
}

test('empty history and an empty selected range have no invented statistics', () => {
  expect(priceHistory([], 'all', instant, 900)).toBeNull();
  expect(priceHistory([recorded(instant - 8 * day, 20000)], '7', instant, 900)).toBeNull();
});

for (const days of [7, 30] as const) {
  test(`the ${days}-day range includes the boundary and excludes older observations`, () => {
    const cutoff = instant - days * day;
    const items = [recorded(cutoff - 1, 5000), recorded(cutoff, 30000), recorded(instant, 25000)];
    const result = priceHistory(items, days === 7 ? '7' : '30', instant, 900)!;
    expect(result.items.map((item) => item.observed_at)).toEqual([cutoff, instant]);
    expect(result.low).toBe(25000);
    expect(result.high).toBe(30000);
    expect(result.change).toBe(-5000);
  });
}

test('comparisons use chronological observations without mutating the source order', () => {
  const latest = recorded(instant, 25000);
  const first = recorded(instant - 1800, 30000);
  const middle = recorded(instant - 900, 20000);
  const input = Object.freeze([latest, first, middle]);
  const result = priceHistory(input, 'all', instant, 900)!;
  expect(input).toEqual([latest, first, middle]);
  expect(result.items).toEqual([first, middle, latest]);
  expect(result.first).toBe(first);
  expect(result.latest).toBe(latest);
  expect(result.low).toBe(20000);
  expect(result.high).toBe(30000);
  expect(result.change).toBe(-5000);
  expect(result.percent).toBeCloseTo(16.6667, 3);
});

test('one recorded price is a finite isolated point with no price movement', () => {
  const item = recorded(instant, 9000);
  const result = priceHistory([item], 'all', instant, 900)!;
  expect(result.low).toBe(9000);
  expect(result.high).toBe(9000);
  expect(result.change).toBe(0);
  expect(result.percent).toBe(0);
  expect(result.endpoints).toHaveLength(1);
  expect(Number.isFinite(result.endpoints[0].x)).toBe(true);
  expect(Number.isFinite(result.endpoints[0].y)).toBe(true);
  expect(result.hasGaps).toBe(false);
});

test('a flat series keeps a horizontal finite line', () => {
  const items = [0, 900, 1800].map((offset) => recorded(instant - 1800 + offset, 20000));
  const result = priceHistory(items, 'all', instant, 900)!;
  const points = result.paths[0].split(' ').map((point) => point.split(',').map(Number));
  expect(points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y))).toBe(true);
  expect(new Set(points.map((point) => point[1])).size).toBe(1);
  expect(result.change).toBe(0);
  expect(result.percent).toBe(0);
  expect(result.hasGaps).toBe(false);
});

test('gaps split only when elapsed time exceeds twice the requested check interval', () => {
  const items = [0, 1800, 3601].map((offset, index) =>
    recorded(instant + offset, 20000 + index * 100),
  );
  const result = priceHistory(items, 'all', instant, 900)!;
  expect(result.paths.map((path) => path.split(' ').length)).toEqual([2, 1]);
  expect(result.endpoints.map((point) => point.observation.observed_at)).toEqual(
    items.map((item) => item.observed_at),
  );
  expect(result.hasGaps).toBe(true);
});

test('chart spacing follows elapsed time instead of observation index', () => {
  const items = [0, 300, 1800].map((offset) => recorded(instant + offset, 20000));
  const result = priceHistory(items, 'all', instant, 900)!;
  const positions = result.paths[0].split(' ').map((point) => Number(point.split(',')[0]));
  expect((positions[1] - positions[0]) / (positions[2] - positions[0])).toBeCloseTo(1 / 6);
});

test('CSV keeps UTC timestamps, minor units, null fares and zero-decimal currencies', () => {
  const csv = historyCsv([recorded(0, 12345, { currency: 'JPY', fare_name: null })]);
  expect(csv).toBe(
    '\uFEFF"observed_at_utc","amount_minor","currency","price_basis","fare","matching_flights","source"\r\n' +
      '"1970-01-01T00:00:00.000Z","12345","JPY","total","","","google_flights"\r\n',
  );
});

test('CSV preserves commas, quotes and line breaks within a single quoted fare field', () => {
  const item = recorded(0, 12500, {
    fare_name: 'Economy, "Flexible"\r\nChange included',
    observed_offer: {
      segments: [
        monitor.target.segments[0],
        {
          date: '2027-03-14',
          legs: [
            { origin: 'DFW', destination: 'DEN', date: '2027-03-14', airline: 'AA', number: '456' },
          ],
        },
      ],
      adults: 1,
      cabin: 1,
      url: monitor.target.url,
    },
  });
  expect(historyCsv([item])).toContain(
    '"1970-01-01T00:00:00.000Z","12500","USD","total","Economy, ""Flexible""\r\nChange included","UA 414, AA 456","google_flights"\r\n',
  );
});

for (const prefix of [
  '=',
  '+',
  '-',
  '@',
  '  =',
  '\t=',
  '\r=',
  '\n=',
  '\u0000=',
  '＝',
  '＋',
  '－',
  '＠',
]) {
  test(`CSV neutralizes formula-leading text ${JSON.stringify(prefix)}`, () => {
    const payload = prefix + 'SUM(1,2)';
    const csv = historyCsv([recorded(0, 12000, { fare_name: payload, source: payload })]);
    const escaped = '"\'' + payload + '"';
    expect(csv).toContain(',' + escaped + ',"",' + escaped + '\r\n');
    expect(csv).not.toContain(',"' + payload + '",');
  });
}

test('CSV exports exactly the supplied view in its existing display order', () => {
  const earlier = recorded(instant - 900, 10000);
  const later = recorded(instant, 15000);
  const csv = historyCsv([later, earlier]);
  expect(csv.indexOf('"15000"')).toBeLessThan(csv.indexOf('"10000"'));
  expect(csv.split('\r\n')).toHaveLength(4);
  expect(historyCsv([]).split('\r\n')).toHaveLength(2);
});
