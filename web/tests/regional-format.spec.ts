import { expect, test } from '@playwright/test';
import {
  currencyFormat,
  departureFormatter,
  observationFormatter,
  validTimeZone,
} from '../src/app/core/regional-formatting';

function parts(formatter: Intl.DateTimeFormat, instant: string): Record<string, string> {
  return Object.fromEntries(
    formatter.formatToParts(new Date(instant)).map(({ type, value }) => [type, value]),
  );
}

test('Chicago spring-forward moves directly from 01:59 to 03:00', () => {
  const formatter = observationFormatter({
    locale: 'en-US',
    time_zone: 'America/Chicago',
    hour_cycle: 'h23',
  });
  expect(parts(formatter, '2026-03-08T07:59:00Z')).toMatchObject({
    hour: '01',
    minute: '59',
    day: '8',
    timeZoneName: 'CST',
  });
  expect(parts(formatter, '2026-03-08T08:00:00Z')).toMatchObject({
    hour: '03',
    minute: '00',
    day: '8',
    timeZoneName: 'CDT',
  });
});

test('Chicago repeated fall-back hour remains distinguishable by its zone label', () => {
  const formatter = observationFormatter({
    locale: 'en-US',
    time_zone: 'America/Chicago',
    hour_cycle: 'h12',
  });
  expect(parts(formatter, '2026-11-01T06:30:00Z')).toMatchObject({
    hour: '1',
    minute: '30',
    dayPeriod: 'AM',
    timeZoneName: 'CDT',
  });
  expect(parts(formatter, '2026-11-01T07:30:00Z')).toMatchObject({
    hour: '1',
    minute: '30',
    dayPeriod: 'AM',
    timeZoneName: 'CST',
  });
});

test('half-hour time zones display the correct local date and minute', () => {
  const formatter = observationFormatter({
    locale: 'en-GB',
    time_zone: 'Asia/Kolkata',
    hour_cycle: 'h23',
  });
  expect(parts(formatter, '2026-11-06T20:45:00Z')).toMatchObject({
    day: '7',
    month: 'Nov',
    year: '2026',
    hour: '02',
    minute: '15',
  });
});

test('explicit clock preferences override regional defaults and h23 starts at zero', () => {
  const twelve = observationFormatter({ locale: 'en-GB', time_zone: 'UTC', hour_cycle: 'h12' });
  const twentyFour = observationFormatter({ locale: 'en-US', time_zone: 'UTC', hour_cycle: 'h23' });
  expect(parts(twelve, '2026-11-06T00:05:00Z')).toMatchObject({ hour: '12', minute: '05' });
  expect(parts(twelve, '2026-11-06T00:05:00Z')['dayPeriod']?.toLowerCase()).toBe('am');
  expect(parts(twentyFour, '2026-11-06T00:05:00Z')).toMatchObject({ hour: '00', minute: '05' });
  expect(parts(twentyFour, '2026-11-06T13:05:00Z')).toMatchObject({ hour: '13', minute: '05' });
  expect(parts(twentyFour, '2026-11-06T13:05:00Z')).not.toHaveProperty('dayPeriod');
});

test('automatic clock format follows the selected region and automatic zone follows the browser', () => {
  const us = observationFormatter({ locale: 'en-US', time_zone: null, hour_cycle: 'auto' });
  const gb = observationFormatter({ locale: 'en-GB', time_zone: null, hour_cycle: 'auto' });
  const browserZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  expect(us.resolvedOptions().timeZone).toBe(browserZone);
  expect(gb.resolvedOptions().timeZone).toBe(browserZone);
  expect(us.resolvedOptions().hour12).toBe(true);
  expect(gb.resolvedOptions().hour12).toBe(false);
});

test('airport departure dates retain their calendar day across the International Date Line', () => {
  // The two displayed observations fall on different days; the trip date stays March 14.
  const instant = '2027-03-14T12:00:00Z';
  const east = observationFormatter({
    locale: 'en-US',
    time_zone: 'Pacific/Kiritimati',
    hour_cycle: 'h23',
  });
  const west = observationFormatter({
    locale: 'en-US',
    time_zone: 'Pacific/Pago_Pago',
    hour_cycle: 'h23',
  });
  expect(parts(east, instant)['day']).toBe('15');
  expect(parts(west, instant)['day']).toBe('14');
  for (const locale of ['en-US', 'en-GB', 'de-DE', 'fr-FR', 'es-ES', 'uk-UA']) {
    const departure = departureFormatter(locale);
    expect(parts(departure, instant)).toMatchObject({ day: '14', year: '2027' });
    expect(departure.resolvedOptions().timeZone).toBe('UTC');
  }
});

test('currency formatting changes separators without changing the quoted currency', () => {
  const dollars = currencyFormat('de-DE', 'USD');
  expect(dollars.resolvedOptions().currency).toBe('USD');
  expect(dollars.formatToParts(1234.56)).toEqual(
    expect.arrayContaining([
      { type: 'group', value: '.' },
      { type: 'decimal', value: ',' },
      { type: 'fraction', value: '56' },
      { type: 'currency', value: '$' },
    ]),
  );
  const yen = currencyFormat('en-US', 'JPY');
  expect(yen.resolvedOptions().currency).toBe('JPY');
  expect(yen.format(12345)).toBe('¥12,345');
  expect(yen.formatToParts(12345).some((part) => part.type === 'fraction')).toBe(false);
});

test('time-zone validation rejects unknown and malformed values without throwing', () => {
  for (const zone of [
    'UTC',
    'America/Chicago',
    'Asia/Kolkata',
    'Asia/Calcutta',
    'Europe/Kyiv',
    'Pacific/Kiritimati',
    'Etc/GMT+5',
  ]) {
    expect(validTimeZone(zone), zone).toBe(true);
  }
  for (const zone of [
    '',
    '   ',
    '+05:30',
    '-06:00',
    '+05',
    '+0530',
    '-2359',
    'Mars/Olympus',
    'America/Does_Not_Exist',
    '../../etc/passwd',
    'posix/America/Chicago',
    'right/UTC',
    'localtime',
    'posixrules',
    'A'.repeat(81),
  ]) {
    expect(validTimeZone(zone), zone).toBe(false);
  }
});
