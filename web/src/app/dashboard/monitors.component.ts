import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { money, timestamp, tripDate } from '../core/format';
import type { Monitor } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { routeName, statusLabel } from './shared/presentation';
import { DialogComponent } from './shared/dialog.component';
import { MonitorEditorComponent } from './monitor-editor.component';
import { PriceHistoryComponent } from './price-history.component';
import { MonitorPresenter } from './monitor-presentation';
import { AirlineComponent } from './shared/airline.component';

@Component({
  selector: 'ff-monitors',
  standalone: true,
  imports: [DialogComponent, MonitorEditorComponent, PriceHistoryComponent, AirlineComponent],
  templateUrl: './monitors.component.html',
  styleUrl: './monitors.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MonitorsComponent {
  readonly workspace = inject(WorkspaceFacade);
  readonly presenter = inject(MonitorPresenter);
  readonly action = new ActionState();
  private readonly api = inject(ApiService);
  readonly money = money;
  readonly timestamp = timestamp;
  readonly tripDate = tripDate;
  readonly routeName = routeName;
  readonly statusLabel = statusLabel;
  readonly creating = signal(false);
  readonly editing = signal<Monitor | null>(null);
  readonly history = signal<Monitor | null>(null);
  readonly stopping = signal<Monitor | null>(null);
  readonly observed = computed(() => this.workspace.active().filter((item) => item.latest).length);
  readonly delayed = computed(
    () =>
      this.workspace
        .active()
        .filter(
          (item) =>
            item.status !== 'paused' && ((item.latest && item.stale) || item.status === 'degraded'),
        ).length,
  );
  current(item: Monitor): boolean {
    return !['cancelled', 'expired'].includes(item.status);
  }
  dates(item: Monitor): string {
    return item.target.segments.map((segment) => tripDate(segment.date)).join(' – ');
  }
  collectionMessage(item: Monitor): string {
    if (item.collection_status === 'blocked') return 'Use Retry collection to try again.';
    if (item.status === 'paused') return 'Resume this monitor when you want to check again.';
    if (!this.current(item)) return 'This monitor is no longer checking prices.';
    return 'We will try again at the next scheduled check.';
  }
  async change(item: Monitor, status: string): Promise<void> {
    await this.action.run(async () => {
      await this.api.request(`/v1/monitors/${item.id}`, { method: 'PATCH', body: { status } });
      await this.workspace.refresh();
      this.stopping.set(null);
    });
  }
  async retry(item: Monitor): Promise<void> {
    await this.action.run(async () => {
      await this.api.request(`/v1/monitors/${item.id}/retry-collection`, { method: 'POST' });
      await this.workspace.refresh();
    });
  }
}
