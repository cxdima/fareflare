import type { Preferences } from './types';

export type DisplaySettings = Pick<Preferences, 'locale' | 'time_zone' | 'hour_cycle'>;

export function validTimeZone(zone: string): boolean {
  // Match the API's IANA-name contract; newer Intl implementations also accept fixed offsets.
  if (
    zone.length > 80 ||
    /^[+-]/.test(zone) ||
    !/^[A-Za-z0-9_+.-]+(?:\/[A-Za-z0-9_+.-]+)*$/.test(zone) ||
    zone.startsWith('posix/') ||
    zone.startsWith('right/') ||
    zone === 'localtime' ||
    zone === 'posixrules'
  )
    return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone }).format(0);
    return true;
  } catch {
    return false;
  }
}

export function observationFormatter(settings: DisplaySettings): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(settings.locale, {
    timeZone: settings.time_zone ?? undefined,
    hourCycle: settings.hour_cycle === 'auto' ? undefined : settings.hour_cycle,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function departureFormatter(locale: string): Intl.DateTimeFormat {
  // Flight departures are airport-calendar dates, not instants in the user's zone.
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

export function clockFormatter(
  settings: Pick<DisplaySettings, 'locale' | 'hour_cycle'>,
): Intl.DateTimeFormat {
  // Flight times are airport clock times, never instants in the reader's zone.
  return new Intl.DateTimeFormat(settings.locale, {
    hourCycle: settings.hour_cycle === 'auto' ? undefined : settings.hour_cycle,
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'UTC',
  });
}

export function currencyFormat(locale: string, currency: string): Intl.NumberFormat {
  return new Intl.NumberFormat(locale, { style: 'currency', currency });
}
