let csrfToken = '';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export function setCsrfToken(value: string) {
  csrfToken = value;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; key?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  if (options.key) headers['Idempotency-Key'] = options.key;
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      signal: options.signal,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('We could not reach the server. Check your connection and try again.', 0);
  }
  const value = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    let detail =
      typeof value?.detail === 'string'
        ? value.detail
        : 'The request could not be completed. Please try again.';
    if (Array.isArray(value?.detail))
      detail = value.detail
        .map(
          (item: { loc?: string[]; msg?: string }) =>
            `${item.loc?.at(-1) ?? 'Input'}: ${item.msg ?? 'Check this value'}`,
        )
        .join('. ');
    if (response.status === 401 && !path.startsWith('/auth/') && path !== '/v1/account') {
      detail = 'Please sign in again to continue.';
      window.dispatchEvent(new Event('session-expired'));
    }
    if (response.status === 429) detail = 'Too many requests. Please wait a minute and try again.';
    throw new ApiError(detail, response.status);
  }
  return value as T;
}

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
