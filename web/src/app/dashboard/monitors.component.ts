import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { PreferencesFacade } from '../core/preferences.facade';
import { RegionalFormat } from '../core/regional-format';
import type { Monitor } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { flightTimes, routeName, statusLabel, travelTime } from './shared/presentation';
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
  /** Technical details are shown only to accounts that asked for them. */
  readonly preferences = inject(PreferencesFacade);
  readonly action = new ActionState();
  private readonly api = inject(ApiService);
  readonly money = (amount: number, currency: string) => this.regional.money(amount, currency);
  readonly regional = inject(RegionalFormat);
  readonly timestamp = this.regional.timestamp;
  readonly tripDate = this.regional.tripDate;
  readonly routeName = routeName;
  readonly statusLabel = statusLabel;
  readonly creating = signal(false);
  readonly editing = signal<Monitor | null>(null);
  readonly history = signal<Monitor | null>(null);
  readonly stopping = signal<Monitor | null>(null);
  readonly query = signal('');
  readonly filter = signal('all');
  readonly filterNames: Record<string, string> = {
    all: 'All flights',
    watching: 'Watching',
    paused: 'Paused',
    attention: 'Needs attention',
    archived: 'Stopped or departed',
  };
  readonly visible = computed(() => {
    const terms = this.query().trim().toLowerCase().split(/\s+/).filter(Boolean);
    return this.workspace.monitors().filter((item) => {
      const filter = this.filter();
      if (filter === 'watching' && (!this.current(item) || item.status === 'paused')) return false;
      if (filter === 'paused' && item.status !== 'paused') return false;
      if (filter === 'archived' && this.current(item)) return false;
      if (filter === 'attention' && !this.needsAttention(item)) return false;
      const presentation = this.presenter.present(item);
      const search = [
        routeName(item),
        presentation.description,
        presentation.match,
        ...item.target.segments.map((segment) => segment.date),
      ]
        .join(' ')
        .toLowerCase();
      return terms.every((term) => search.includes(term));
    });
  });
  current(item: Monitor): boolean {
    return !['cancelled', 'expired'].includes(item.status);
  }
  needsAttention(item: Monitor): boolean {
    return (
      this.current(item) &&
      item.status !== 'paused' &&
      ((!!item.latest && item.stale) ||
        item.status === 'degraded' ||
        item.collection_status === 'blocked')
    );
  }
  clearFilters(): void {
    this.query.set('');
    this.filter.set('all');
  }
  dates(item: Monitor): string {
    return item.target.segments.map((segment) => this.tripDate(segment.date)).join(' – ');
  }
  /** One line per direction: what is shown, and the same fact phrased for a screen reader. */
  times(item: Monitor): { text: string; spoken: string }[] {
    const schedule = flightTimes(item);
    return schedule.map((slice, index) => {
      const departs = this.regional.clock(slice.departs);
      const arrives = this.regional.clock(slice.arrives);
      const later = slice.arrival_day_offset ?? 0;
      const duration = travelTime(slice.duration_minutes);
      const returning = schedule.length > 1 && index > 0;
      return {
        text:
          (returning ? '↩ ' : '') +
          `${departs} → ${arrives}` +
          (later > 0 ? ` +${later}` : '') +
          (duration ? ` · ${duration}` : ''),
        spoken:
          (returning ? 'Return departs ' : 'Departs ') +
          `${departs}, arrives ${arrives}` +
          (later > 0 ? `, ${later} ${later === 1 ? 'day' : 'days'} later` : '') +
          (duration ? `, ${duration}` : ''),
      };
    });
  }
  collectionMessage(item: Monitor): string {
    if (!this.current(item)) return 'This monitor is no longer checking prices.';
    if (item.status === 'paused') return 'Resume this monitor when you want to check again.';
    if (item.collection_status === 'blocked') return 'Use Retry collection to try again.';
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
