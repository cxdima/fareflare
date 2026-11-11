import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { ApiService } from '../core/api.service';
import { PreferencesFacade } from '../core/preferences.facade';
import { RegionalFormat } from '../core/regional-format';
import { TelegramFacade } from '../core/telegram.facade';
import { takePendingLink } from '../core/flight-link';
import type { Monitor } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { flightTimes, routeName, statusLabel, travelTime } from './shared/presentation';
import { DialogComponent } from './shared/dialog.component';
import { MonitorEditorComponent } from './monitor-editor.component';
import { PriceHistoryComponent } from './price-history.component';
import { PriceStripComponent } from './price-strip.component';
import { MonitorPresenter } from './monitor-presentation';
import { AirlineComponent } from './shared/airline.component';
import { TelegramConnectComponent } from './shared/telegram-connect.component';

const DAY = 86400;

@Component({
  selector: 'ff-monitors',
  standalone: true,
  imports: [
    DialogComponent,
    MonitorEditorComponent,
    PriceHistoryComponent,
    PriceStripComponent,
    AirlineComponent,
    TelegramConnectComponent,
  ],
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
  readonly telegram = inject(TelegramFacade);
  /** Advances so "5 minutes ago" stays true while the page is left open. */
  readonly now = signal(Date.now());
  private readonly inviteKey = 'fareflare.telegram-invite.' + this.workspace.session.account()?.id;
  private readonly inviteDeclined = signal(this.stored());
  /** Stays up once offered, so the result of connecting is seen where it was started. */
  private readonly inviteOffered = signal(false);
  readonly inviting = computed(() => this.inviteOffered() && !this.inviteDeclined());
  /** A new account with nothing watched yet: the page is one invitation to add a flight. */
  readonly firstRun = computed(
    () =>
      this.workspace.monitorsLoaded() &&
      !this.workspace.monitors().length &&
      !this.workspace.activeCount(),
  );
  readonly creating = signal(false);
  /** A link pasted on the website before signing in: the dialog opens with it filled in. */
  readonly pendingLink = signal('');
  private pendingRead = false;
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
  /** One mark per monitor the account may have: filled when in use, hatched when free. */
  readonly slots = computed(() => {
    const limit = Math.min(this.workspace.session.config()?.limits.monitors ?? 0, 30);
    const used = this.workspace.activeCount();
    return Array.from({ length: limit }, (_, index) => index < used);
  });
  /** With room left and nothing filtered away, the list ends in an empty slot to fill. */
  readonly freeSlot = computed(
    () =>
      this.workspace.monitorsLoaded() &&
      !this.atLimit() &&
      !this.query() &&
      this.filter() === 'all' &&
      !this.workspace.monitorCursor() &&
      this.visible().length > 0,
  );
  constructor() {
    const clock = setInterval(() => this.now.set(Date.now()), 30000);
    inject(DestroyRef).onDestroy(() => clearInterval(clock));
    void this.telegram.load();
    effect(() => {
      if (!this.workspace.monitorsLoaded() || this.pendingRead) return;
      this.pendingRead = true;
      untracked(() => {
        const link = takePendingLink();
        if (!link || this.atLimit()) return;
        this.pendingLink.set(link);
        this.creating.set(true);
      });
    });
    effect(() => {
      const status = this.telegram.status();
      // Offered once someone has a flight to be told about and nowhere to be told.
      if (status?.enabled && !status.connected && this.workspace.active().length)
        this.inviteOffered.set(true);
    });
  }
  declineInvite(): void {
    this.inviteDeclined.set(true);
    try {
      localStorage.setItem(this.inviteKey, 'hidden');
    } catch {
      // Private browsing: the choice lasts for this visit only.
    }
  }
  private stored(): boolean {
    try {
      return localStorage.getItem(this.inviteKey) === 'hidden';
    } catch {
      return false;
    }
  }
  /** Where the latest price stands against the lowest this monitor has recorded. */
  lowNote(item: Monitor): { atLow: boolean; text: string } | null {
    const latest = item.latest;
    const low = item.low_minor;
    if (!latest || low == null || !item.created_at) return null;
    const since = this.regional.day(item.created_at);
    if (latest.amount_minor > low)
      return { atLow: false, text: `Low since ${since}: ${this.money(low, latest.currency)}` };
    // On the first day the only price is trivially the lowest; say nothing yet.
    return latest.observed_at - item.created_at >= DAY
      ? { atLow: true, text: `Lowest since ${since}` }
      : null;
  }
  /** Every monitor the account may have is in use, so the add action is unavailable. */
  atLimit(): boolean {
    return this.workspace.activeCount() >= this.workspace.session.config()!.limits.monitors;
  }
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
  /**
   * Whether failed checks are worth a note. One failed check is retried within a
   * couple of minutes and usually succeeds, so it is not; a run of them is, and so
   * is a stop. A service that does not count failures keeps the note.
   */
  failing(item: Monitor): boolean {
    return (
      !!item.last_error &&
      (item.collection_status === 'blocked' || (item.collection_failures ?? 2) > 1)
    );
  }
  collectionMessage(item: Monitor): string {
    if (!this.current(item)) return 'This monitor is no longer checking prices.';
    if (item.status === 'paused') return 'Resume this monitor when you want to check again.';
    if (item.collection_status === 'blocked') return 'Use Retry collection to try again.';
    return 'We will keep trying.';
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
