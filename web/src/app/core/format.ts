export const requestKey = () => crypto.randomUUID();
export const message = (error: unknown) =>
  error instanceof Error ? error.message : 'Something went wrong. Please try again.';
export function safeFlightUrl(url: string): string | undefined {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' &&
      ['google.com', 'www.google.com'].includes(parsed.hostname) &&
      parsed.pathname.startsWith('/travel/flights')
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}
