import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ApiService } from '../core/api.service';
import { RegionalFormat } from '../core/regional-format';
import type { Monitor, Observation, Page } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { flightNumbers, routeName } from './shared/presentation';
import { historyCsv, priceHistory, type HistoryRange } from './price-history';

@Component({
  selector: 'ff-price-history',
  standalone: true,
  imports: [DialogComponent],
  templateUrl: './price-history.component.html',
  styleUrl: './price-history.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PriceHistoryComponent implements OnInit, OnDestroy {
  readonly monitor = input.required<Monitor>();
  readonly closed = output<void>();
  readonly action = new ActionState();
  readonly items = signal<Observation[]>([]);
  readonly cursor = signal<string | null>(null);
  readonly loaded = signal(false);
  readonly range = signal<HistoryRange>('all');
  readonly ranges = [
    { value: 'all' as const, label: 'All loaded' },
    { value: '7' as const, label: 'Past 7 days' },
    { value: '30' as const, label: 'Past 30 days' },
  ];
  readonly money = (amount: number, currency: string) => this.regional.money(amount, currency);
  readonly regional = inject(RegionalFormat);
  readonly timestamp = this.regional.timestamp;
  readonly routeName = routeName;
  readonly flightNumbers = flightNumbers;
  private readonly api = inject(ApiService);
  private readonly controller = new AbortController();
  private readonly openedAt = Math.floor(Date.now() / 1000);
  readonly view = computed(() =>
    priceHistory(this.items(), this.range(), this.openedAt, this.monitor().interval_seconds),
  );
  readonly rows = computed(() => [...(this.view()?.items ?? [])].reverse());
  readonly chartLabel = computed(() => {
    const view = this.view();
    return view
      ? `Observed price history, from ${this.money(view.first.amount_minor, view.first.currency)} to ${this.money(view.latest.amount_minor, view.latest.currency)}. ${view.items.length} observations. Long gaps are not connected. All values are in the table below.`
      : '';
  });
  readonly changeLabel = computed(() => {
    const view = this.view();
    if (!view || view.items.length < 2) return 'One observation so far';
    if (view.change === 0) return 'Unchanged from the first price shown';
    const percent = this.regional.number(view.percent);
    return `${view.change < 0 ? 'Down' : 'Up'} ${this.money(Math.abs(view.change), view.latest.currency)} (${percent}%) from the first price shown`;
  });

  ngOnInit(): void {
    void this.load();
  }
  ngOnDestroy(): void {
    this.controller.abort();
  }
  async load(next?: string): Promise<void> {
    await this.action.run(async () => {
      const page = await this.api.request<Page<Observation>>(
        `/v1/monitors/${this.monitor().id}/history${next ? '?cursor=' + encodeURIComponent(next) : ''}`,
        { signal: this.controller.signal },
      );
      const merged = next ? [...this.items(), ...page.items] : page.items;
      this.items.set(
        [...new Map(merged.map((item) => [item.observed_at, item])).values()].sort(
          (a, b) => b.observed_at - a.observed_at,
        ),
      );
      this.cursor.set(page.next_cursor ?? null);
      this.loaded.set(true);
    });
  }
  download(): void {
    const url = URL.createObjectURL(
      new Blob([historyCsv(this.rows())], { type: 'text/csv;charset=utf-8' }),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `fareflare-${this.monitor().id}-prices.csv`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
