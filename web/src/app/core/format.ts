export const requestKey = () => crypto.randomUUID();
export const message = (error: unknown) =>
  error instanceof Error ? error.message : 'Something went wrong. Please try again.';
export const money = (amount: number, currency: string) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
    amount / (currency === 'JPY' ? 1 : 100),
  );
export const timestamp = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
export const tripDate = (value: string) =>
  new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });

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
