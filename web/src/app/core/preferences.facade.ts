import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { message } from './format';
import type { Preferences } from './types';

export const defaultPreferences: Preferences = {
  muted: false,
  muted_routes: [],
  time_zone: null,
  locale: 'en-US',
  hour_cycle: 'auto',
  telegram_style: 'detailed',
  telegram_templates: {},
  telegram_show_flight_numbers: true,
  telegram_show_times: true,
  telegram_show_observed_time: true,
  telegram_show_fare: true,
  telegram_show_buttons: true,
  telegram_silent: false,
  diagnostics: false,
};

/** Dashboard-scoped preferences: never retained across account/session changes. */
@Injectable()
export class PreferencesFacade {
  private readonly api = inject(ApiService);
  private readonly controller = new AbortController();
  private pending: Promise<Preferences> | null = null;
  readonly value = signal<Preferences>({ ...defaultPreferences });
  readonly loaded = signal(false);
  readonly saving = signal(false);
  readonly error = signal('');

  constructor() {
    inject(DestroyRef).onDestroy(() => this.controller.abort());
  }

  load(): Promise<Preferences> {
    if (this.loaded()) return Promise.resolve(this.value());
    if (this.pending) return this.pending;
    this.error.set('');
    this.pending = this.api
      .request<Preferences>('/v1/preferences', { signal: this.controller.signal })
      .then((value) => {
        this.value.set({ ...defaultPreferences, ...value });
        this.loaded.set(true);
        return this.value();
      })
      .catch((error: unknown) => {
        this.error.set(message(error));
        throw error;
      })
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }

  async save(changes: Partial<Preferences>): Promise<Preferences> {
    if (!this.loaded()) throw new Error('Load your settings before saving changes.');
    if (this.saving()) throw new Error('Your previous settings are still being saved.');
    this.saving.set(true);
    try {
      const value = await this.api.request<Preferences>('/v1/preferences', {
        method: 'PUT',
        body: changes,
        signal: this.controller.signal,
      });
      this.value.update((previous) => ({ ...previous, ...value }));
      return this.value();
    } finally {
      this.saving.set(false);
    }
  }
}
