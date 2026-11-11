import { Injectable, inject, signal } from '@angular/core';
import { ApiError, ApiService } from './api.service';
import { Account, AccountResponse, ProductConfig } from './types';
import { message } from './format';

/** One session boundary for auth, dashboard and consent. Secrets never enter storage. */
@Injectable({ providedIn: 'root' })
export class SessionFacade {
  private readonly api = inject(ApiService);
  readonly config = signal<ProductConfig | null>(null);
  readonly account = signal<Account | null>(null);
  readonly ready = signal(false);
  readonly error = signal('');
  /** True after a deliberate sign-out or deletion: the next sign-in starts from the top. */
  readonly left = signal(false);
  private boot: Promise<void> | null = null;

  constructor() {
    window.addEventListener('session-expired', () => this.clear());
  }

  bootstrap(): Promise<void> {
    if (this.boot) return this.boot;
    this.ready.set(false);
    this.boot = this.load();
    return this.boot;
  }

  private async load(): Promise<void> {
    this.error.set('');
    try {
      this.config.set(await this.api.request<ProductConfig>('/v1/config'));
      try {
        this.accept(await this.api.request<AccountResponse>('/v1/account'));
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) throw error;
      }
    } catch (error) {
      this.error.set(message(error));
      this.boot = null;
    } finally {
      this.ready.set(true);
    }
  }

  accept(result: AccountResponse): void {
    this.api.setCsrfToken(result.csrf_token);
    this.account.set(result.account);
    this.error.set('');
    this.left.set(false);
  }

  /** Ends the session on purpose, as opposed to finding that it expired. */
  leave(): void {
    this.left.set(true);
    this.clear();
  }

  clear(): void {
    this.api.setCsrfToken('');
    this.account.set(null);
  }
}
