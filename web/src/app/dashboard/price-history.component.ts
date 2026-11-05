import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ApiService } from '../core/api.service';
import { money, timestamp } from '../core/format';
import type { Monitor, Observation, Page } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { flightNumbers, routeName } from './shared/presentation';

@Component({
  selector: 'ff-price-history',
  standalone: true,
  imports: [DialogComponent],
  templateUrl: './price-history.component.html',
  styleUrl: './price-history.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PriceHistoryComponent implements OnInit {
  readonly monitor = input.required<Monitor>();
  readonly closed = output<void>();
  readonly action = new ActionState();
  readonly items = signal<Observation[]>([]);
  readonly cursor = signal<string | null>(null);
  readonly money = money;
  readonly timestamp = timestamp;
  readonly routeName = routeName;
  readonly flightNumbers = flightNumbers;
  private readonly api = inject(ApiService);
  readonly ordered = computed(() =>
    [...this.items()].sort((a, b) => a.observed_at - b.observed_at),
  );
  readonly low = computed(() => Math.min(...this.items().map((item) => item.amount_minor)));
  readonly chartLabel = computed(() => {
    const items = this.ordered();
    return items.length
      ? `Observed price history, from ${money(items[0].amount_minor, this.monitor().target.currency)} to ${money(items[items.length - 1].amount_minor, this.monitor().target.currency)}. All values are in the table below.`
      : '';
  });
  readonly points = computed(() => {
    const items = this.ordered();
    if (!items.length) return '';
    const low = this.low();
    const high = Math.max(...items.map((item) => item.amount_minor));
    const start = items[0].observed_at;
    const end = items[items.length - 1].observed_at;
    return items
      .map(
        (item) =>
          `${30 + ((item.observed_at - start) / (end - start || 1)) * 640},${145 - ((item.amount_minor - low) / (high - low || 1)) * 115}`,
      )
      .join(' ');
  });
  ngOnInit(): void {
    void this.load();
  }
  async load(next?: string): Promise<void> {
    await this.action.run(async () => {
      const page = await this.api.request<Page<Observation>>(
        `/v1/monitors/${this.monitor().id}/history${next ? '?cursor=' + encodeURIComponent(next) : ''}`,
      );
      this.items.update((previous) => (next ? [...previous, ...page.items] : page.items));
      this.cursor.set(page.next_cursor ?? null);
    });
  }
}
