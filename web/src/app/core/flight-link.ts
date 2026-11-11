/** What can be said about a pasted link before the service has seen it. */
export interface LinkNote {
  ok: boolean;
  text: string;
}

/** Says at once whether what was pasted can be a flight link; the service decides the rest. */
export function flightLinkNote(value: string): LinkNote | null {
  const text = value.trim();
  if (!text) return null;
  let link: URL;
  try {
    link = new URL(text);
  } catch {
    return { ok: false, text: 'Paste the whole link, starting with https://' };
  }
  return link.protocol === 'https:' &&
    ['google.com', 'www.google.com'].includes(link.hostname) &&
    link.pathname.startsWith('/travel/flights')
    ? { ok: true, text: 'Google Flights link recognized.' }
    : {
        ok: false,
        text: 'That is not a Google Flights link. Copy it from google.com/travel/flights.',
      };
}

const PENDING = 'fareflare.pending-link';

/** A link pasted on the website waits in this tab until its owner can watch it. */
export function keepPendingLink(url: string): void {
  try {
    sessionStorage.setItem(PENDING, url.trim());
  } catch {
    // Storage is unavailable: the link is pasted again after signing up.
  }
}

/** Returns the waiting link once, and only if it still looks like a flight link. */
export function takePendingLink(): string {
  try {
    const url = sessionStorage.getItem(PENDING) ?? '';
    sessionStorage.removeItem(PENDING);
    return flightLinkNote(url)?.ok ? url : '';
  } catch {
    return '';
  }
}
