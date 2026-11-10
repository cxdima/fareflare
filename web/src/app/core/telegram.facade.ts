import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import { ActionState } from '../dashboard/shared/action-state';

export type TelegramStatus = { enabled: boolean; connected: boolean; bot_username?: string };

const CHECK_EVERY = 4000;
// A connect link is valid for ten minutes; stop asking once it cannot work.
const LINK_LIFETIME = 10 * 60_000;

/** The account's Telegram connection, shared by every place that offers to set it up. */
@Injectable()
export class TelegramFacade {
  private readonly api = inject(ApiService);
  readonly status = signal<TelegramStatus | null>(null);
  /** A one-time link to the bot, present while a connection is being made. */
  readonly link = signal('');
  /** True while the page is checking whether Start was pressed in Telegram. */
  readonly waiting = signal(false);
  readonly action = new ActionState();
  private timer: ReturnType<typeof setInterval> | undefined;
  private loading: Promise<unknown> | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopWaiting());
  }

  /** Reads the connection once; later callers share the same answer. */
  load(): Promise<unknown> {
    return (this.loading ??= this.action.run(() => this.read()));
  }

  async connect(): Promise<void> {
    await this.action.run(async () => {
      const result = await this.api.request<{ url: string }>('/v1/telegram', { method: 'POST' });
      const url = new URL(result.url);
      if (url.protocol !== 'https:' || url.hostname !== 't.me')
        throw new Error('The server returned an invalid Telegram link.');
      this.link.set(url.href);
      this.wait();
    });
  }

  async check(): Promise<void> {
    await this.action.run(() => this.read());
  }

  async disconnect(): Promise<void> {
    await this.action.run(async () => {
      await this.api.request('/v1/telegram', { method: 'DELETE' });
      this.link.set('');
      this.stopWaiting();
      await this.read();
    });
  }

  private async read(): Promise<void> {
    const value = await this.api.request<TelegramStatus>('/v1/telegram');
    this.status.set(value);
    if (value.connected) {
      this.link.set('');
      this.stopWaiting();
    }
  }

  /** Notices the connection by itself, so nobody has to come back and press a button. */
  private wait(): void {
    this.stopWaiting();
    this.waiting.set(true);
    const started = Date.now();
    this.timer = setInterval(() => {
      if (Date.now() - started > LINK_LIFETIME) {
        this.link.set('');
        return this.stopWaiting();
      }
      if (document.visibilityState === 'visible') void this.read().catch(() => undefined);
    }, CHECK_EVERY);
  }

  private stopWaiting(): void {
    clearInterval(this.timer);
    this.timer = undefined;
    this.waiting.set(false);
  }
}
