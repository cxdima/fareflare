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

@Component({
  selector: 'ff-monitors',
  standalone: true,
  imports: [DialogComponent, MonitorEditorComponent, PriceHistoryComponent],
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
    () => this.workspace.active().filter((item) => item.stale || item.status === 'degraded').length,
  );
  current(item: Monitor): boolean {
    return !['cancelled', 'expired'].includes(item.status);
  }
  dates(item: Monitor): string {
    return item.target.segments.map((segment) => tripDate(segment.date)).join(' · ');
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
