import type { AdminFlight, AuditEntry, Monitor } from '../../core/types';

/** What each recorded admin action did, in the past tense the activity log reads in. */
export const actionLabels: Record<string, string> = {
  suspend: 'Suspended the account',
  reactivate: 'Reactivated the account',
  'sign-out': 'Signed the account out everywhere',
  'reset-two-factor': 'Turned off two-step sign-in',
  'temporary-password': 'Issued a temporary password',
  delete: 'Deleted the account',
  'pause-flight': 'Paused a flight',
  'resume-flight': 'Resumed a flight',
  'stop-flight': 'Stopped a flight',
  switches: 'Changed a service switch',
};

const switchLabels: Record<string, [string, string]> = {
  registration_paused: ['Sign-ups paused', 'Sign-ups resumed'],
  collection_paused: ['Price checks paused', 'Price checks resumed'],
};

/** The detail an entry carries: a route, a switch, or the reason given. */
export function auditDetail(entry: AuditEntry): string {
  const parts: string[] = [];
  if (typeof entry.detail['route'] === 'string') parts.push(entry.detail['route']);
  for (const [key, labels] of Object.entries(switchLabels))
    if (typeof entry.detail[key] === 'boolean') parts.push(labels[entry.detail[key] ? 0 : 1]);
  if (typeof entry.detail['reason'] === 'string') parts.push(`“${entry.detail['reason']}”`);
  return parts.join(' · ');
}

export const accountStatusLabels: Record<string, string> = {
  active: 'Active',
  suspended: 'Suspended',
  deleted: 'Deleted',
};

/** Sticker tones reuse the flight vocabulary: lime is fine, violet needs a look. */
export const accountStatusTone: Record<string, string> = {
  active: 'active',
  suspended: 'degraded',
  deleted: 'cancelled',
};

export const flightStateLabels: Record<AdminFlight['state'], string> = {
  collecting: 'Checking',
  blocked: 'Blocked',
  idle: 'No watchers',
};

export const flightStateTone: Record<AdminFlight['state'], string> = {
  collecting: 'active',
  blocked: 'degraded',
  idle: 'paused',
};

export function routeOf(target: Monitor['target']): string {
  const legs = target.segments[0]?.legs ?? [];
  return legs.length ? `${legs[0].origin} → ${legs[legs.length - 1].destination}` : 'Itinerary';
}

/** "Round trip · 2 adults", the shape of a trip without its codes. */
export function tripShape(target: Monitor['target']): string {
  const trip = target.segments.length > 1 ? 'Round trip' : 'One way';
  const people = target.adults === 1 ? '1 adult' : `${target.adults} adults`;
  return `${trip} · ${people}`;
}

export function share(part: number, total: number): string {
  return total ? `${Math.round((part / total) * 100)}%` : '–';
}
