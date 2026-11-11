import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { ApiService } from '../core/api.service';
import { RegionalFormat } from '../core/regional-format';
import type { Monitor, Observation, Page } from '../core/types';
import { STRIP, priceStrip } from './price-strip';

const RECENT = 48;

/**
 * The recent recorded prices of one flight as a row of bars on its tag. It loads when the
 * tag comes into view and again when a new price is recorded; if it cannot load, the tag
 * simply goes without it, because the full history is one button away.
 */
@Component({
  selector: 'ff-price-strip',
  templateUrl: './price-strip.component.html',
  styleUrl: './price-strip.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PriceStripComponent {
  readonly monitor = input.required<Monitor>();
  /** The current time in milliseconds, shared with the tag so both age together. */
  readonly now = input.required<number>();
  readonly strip = STRIP;
  readonly width = STRIP.slots * STRIP.step - (STRIP.step - STRIP.bar);
  private readonly api = inject(ApiService);
  private readonly regional = inject(RegionalFormat);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
  private readonly controller = new AbortController();
  private readonly items = signal<Observation[]>([]);
  private readonly seen = signal(false);
  private loadedFor = -1;
  private near?: IntersectionObserver;
  readonly hatch = computed(() => 'strip-' + this.monitor().id.replace(/[^a-zA-Z0-9_-]/g, ''));
  readonly hatchFill = computed(() => `url(#${this.hatch()})`);
  readonly view = computed(() => priceStrip(this.items(), this.monitor().interval_seconds));
  readonly since = computed(() => {
    const view = this.view();
    return view ? this.regional.ago(view.first.observed_at, this.now()) : '';
  });
  readonly label = computed(() => {
    const view = this.view();
    if (!view) return '';
    const currency = view.latest.currency;
    const range =
      view.low === view.high
        ? `every recorded total was ${this.regional.money(view.low, currency)}`
        : `lowest ${this.regional.money(view.low, currency)}, highest ${this.regional.money(view.high, currency)}`;
    const gaps = view.gaps ? ' Hatched bars are times with no recorded price.' : '';
    return `Recorded prices since ${this.regional.timestamp(view.first.observed_at)}: ${range}.${gaps}`;
  });

  constructor() {
    afterNextRender(() => {
      const near = new IntersectionObserver(
        (entries) => {
          if (!entries.some((entry) => entry.isIntersecting)) return;
          near.disconnect();
          this.seen.set(true);
        },
        { rootMargin: '200px 0px' },
      );
      near.observe(this.host);
      this.near = near;
    });
    effect(() => {
      const recorded = this.monitor().latest?.observed_at ?? 0;
      if (!this.seen() || !recorded || recorded === this.loadedFor) return;
      this.loadedFor = recorded;
      void this.load();
    });
    inject(DestroyRef).onDestroy(() => {
      this.near?.disconnect();
      this.controller.abort();
    });
  }

  private async load(): Promise<void> {
    try {
      const page = await this.api.request<Page<Observation>>(
        `/v1/monitors/${this.monitor().id}/history?limit=${RECENT}`,
        { signal: this.controller.signal },
      );
      this.items.set(page.items);
    } catch {
      // The strip is a glance, not the record: the tag stays as it was.
    }
  }
}
