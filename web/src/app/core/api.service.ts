import { Injectable } from '@angular/core';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  key?: string;
  signal?: AbortSignal;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private csrfToken = '';

  setCsrfToken(value: string): void {
    this.csrfToken = value;
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = options.method ?? 'GET';
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && this.csrfToken) headers['X-CSRF-Token'] = this.csrfToken;
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
          .map((item: { loc?: string[]; msg?: string; type?: string }) =>
            // The service's own validation messages are complete sentences.
            item.type === 'value_error' && item.msg
              ? item.msg.replace(/^Value error, /, '')
              : `${item.loc?.at(-1) ?? 'Input'}: ${item.msg ?? 'Check this value'}`,
          )
          .join('. ');
      if (response.status === 401 && !path.startsWith('/auth/') && path !== '/v1/account') {
        detail = 'Please sign in again to continue.';
        window.dispatchEvent(new Event('session-expired'));
      }
      if (response.status === 429)
        detail = 'Too many requests. Please wait a minute and try again.';
      throw new ApiError(detail, response.status);
    }
    return value as T;
  }
}
