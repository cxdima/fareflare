import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { message } from '../core/format';
import type { Monitor, Page, Webhook } from '../core/types';

type MonitorPage = Page<Monitor> & { active_count?: number };
type LoadedMonitors = {
  items: Monitor[];
  cursor: string | null;
  activeCount: number | null;
  pages: number;
};

/** Keeps workspace reads separate from presentation and mutation commands. */
@Injectable()
export class WorkspaceFacade {
  readonly api = inject(ApiService);
  readonly session = inject(SessionFacade);
  readonly monitors = signal<Monitor[]>([]);
  readonly monitorsLoaded = signal(false);
  readonly webhooks = signal<Webhook[]>([]);
  readonly refreshing = signal(false);
  readonly error = signal('');
  readonly monitorCursor = signal<string | null>(null);
  readonly loadingMoreMonitors = signal(false);
  readonly monitorLoadError = signal('');
  readonly active = computed(() =>
    this.monitors().filter((item) => !['cancelled', 'expired'].includes(item.status)),
  );
  private readonly accountActiveCount = signal<number | null>(null);
  readonly activeCount = computed(() => this.accountActiveCount() ?? this.active().length);
  private loadedPages = 1;
  private generation = 0;
  private controller: AbortController | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      this.generation++;
      this.controller?.abort();
    });
  }

  async refresh(): Promise<void> {
    if (!this.session.account()) return;
    const generation = ++this.generation;
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    this.refreshing.set(true);
    this.loadingMoreMonitors.set(false);
    this.error.set('');
    this.monitorLoadError.set('');
    const results = await Promise.allSettled([
      this.readMonitorPages(this.loadedPages, controller.signal),
      this.api.request<Page<Webhook>>('/v1/webhooks?limit=100', { signal: controller.signal }),
    ]);
    if (generation !== this.generation) return;
    if (results[0].status === 'fulfilled') {
      const loaded = results[0].value;
      this.monitors.set(loaded.items);
      this.monitorsLoaded.set(true);
      this.monitorCursor.set(loaded.cursor);
      this.accountActiveCount.set(loaded.activeCount);
      this.loadedPages = loaded.pages;
    }
    if (results[1].status === 'fulfilled') this.webhooks.set(results[1].value.items);
    const failed = results.find((result) => result.status === 'rejected');
    this.error.set(failed?.status === 'rejected' ? message(failed.reason) : '');
    this.refreshing.set(false);
    this.controller = null;
  }

  async loadMoreMonitors(): Promise<void> {
    const cursor = this.monitorCursor();
    if (!cursor || !this.session.account() || this.refreshing() || this.loadingMoreMonitors())
      return;
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.loadingMoreMonitors.set(true);
    this.monitorLoadError.set('');
    try {
      const page = await this.readMonitorPage(cursor, controller.signal);
      if (generation !== this.generation) return;
      this.monitors.update((previous) => this.uniqueMonitors([...previous, ...page.items]));
      this.monitorCursor.set(page.next_cursor ?? null);
      if (page.active_count !== undefined) this.accountActiveCount.set(page.active_count);
      this.loadedPages++;
    } catch (error) {
      if (generation === this.generation) this.monitorLoadError.set(message(error));
    } finally {
      if (generation === this.generation) {
        this.loadingMoreMonitors.set(false);
        this.controller = null;
      }
    }
  }

  private async readMonitorPages(depth: number, signal: AbortSignal): Promise<LoadedMonitors> {
    const loaded: LoadedMonitors = { items: [], cursor: null, activeCount: null, pages: 0 };
    for (let index = 0; index < depth; index++) {
      const page = await this.readMonitorPage(loaded.cursor, signal);
      loaded.items.push(...page.items);
      loaded.cursor = page.next_cursor ?? null;
      if (page.active_count !== undefined) loaded.activeCount = page.active_count;
      loaded.pages++;
      if (!loaded.cursor) break;
    }
    loaded.items = this.uniqueMonitors(loaded.items);
    return loaded;
  }

  private readMonitorPage(cursor: string | null, signal: AbortSignal): Promise<MonitorPage> {
    const query = new URLSearchParams({ limit: '100' });
    if (cursor) query.set('cursor', cursor);
    return this.api.request<MonitorPage>('/v1/monitors?' + query, { signal });
  }

  private uniqueMonitors(items: Monitor[]): Monitor[] {
    return [...new Map(items.map((item) => [item.id, item])).values()];
  }
}
