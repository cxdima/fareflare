import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { message } from '../core/format';
import type { Monitor, Page, Webhook } from '../core/types';

/** Keeps workspace reads separate from presentation and mutation commands. */
@Injectable()
export class WorkspaceFacade {
  readonly api = inject(ApiService);
  readonly session = inject(SessionFacade);
  readonly monitors = signal<Monitor[]>([]);
  readonly webhooks = signal<Webhook[]>([]);
  readonly refreshing = signal(false);
  readonly error = signal('');
  readonly active = computed(() =>
    this.monitors().filter((item) => !['cancelled', 'expired'].includes(item.status)),
  );

  async refresh(): Promise<void> {
    if (!this.session.account() || this.refreshing()) return;
    this.refreshing.set(true);
    const results = await Promise.allSettled([
      this.api.request<Page<Monitor>>('/v1/monitors?limit=100'),
      this.api.request<Page<Webhook>>('/v1/webhooks?limit=100'),
    ]);
    if (results[0].status === 'fulfilled') this.monitors.set(results[0].value.items);
    if (results[1].status === 'fulfilled') this.webhooks.set(results[1].value.items);
    const failed = results.find((result) => result.status === 'rejected');
    this.error.set(failed?.status === 'rejected' ? message(failed.reason) : '');
    this.refreshing.set(false);
  }
}
