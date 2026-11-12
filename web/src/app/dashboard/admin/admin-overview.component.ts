import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import { ApiService } from '../../core/api.service';
import { RegionalFormat } from '../../core/regional-format';
import type { AdminOverview, StatusHour } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { statusLabel } from '../shared/presentation';
import { share } from './admin-labels';
import type { AdminTab } from './admin.component';

/** The order flights are counted in: the ones being watched first. */
const flightStates = ['active', 'pending', 'degraded', 'paused'] as const;

@Component({
  selector: 'ff-admin-overview',
  standalone: true,
  templateUrl: './admin-overview.component.html',
  styleUrl: './admin-overview.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminOverviewComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly format = inject(RegionalFormat);
  readonly go = output<AdminTab>();
  readonly data = signal<AdminOverview | null>(null);
  readonly action = new ActionState();
  readonly share = share;
  readonly statusLabel = statusLabel;

  readonly peak = computed(() =>
    Math.max(1, ...(this.data()?.signups.map((item) => item.count) ?? [1])),
  );
  readonly slots = computed(() => {
    const capacity = this.data()?.flights.capacity;
    if (!capacity?.limit) return [];
    return Array.from({ length: capacity.limit }, (_, index) => index < capacity.used);
  });
  readonly flightCounts = computed(() => {
    const counts = this.data()?.flights.by_status ?? {};
    return flightStates
      .map((state) => ({ state, count: counts[state] ?? 0 }))
      .filter((item) => item.count);
  });
  readonly checks = computed(() => {
    const hours = this.data()?.collection.hours ?? [];
    const collected = hours.reduce((sum, hour) => sum + hour.collected, 0);
    const failed = hours.reduce((sum, hour) => sum + hour.failed, 0);
    const alerts = hours.reduce((sum, hour) => sum + hour.alerts_sent, 0);
    const component = this.data()?.collection.components.find((item) => item.id === 'price_checks');
    return { collected, failed, alerts, last: component?.last_run_at ?? null };
  });
  readonly adoption = computed(() => {
    const users = this.data()?.users;
    if (!users) return [];
    return [
      { label: 'Confirmed email', count: users.email_verified },
      { label: 'Two-step sign-in', count: users.two_factor },
      { label: 'A passkey', count: users.passkeys },
      { label: 'Telegram alerts', count: users.telegram },
      { label: 'An API key', count: users.api_keys },
    ].map((item) => ({ ...item, part: users.total ? item.count / users.total : 0 }));
  });
  readonly budgets = computed(() => {
    const email = this.data()?.email;
    if (!email) return [];
    return [
      { label: 'Confirmations', ...email.confirm },
      { label: 'Password resets', ...email.reset },
      { label: 'Security notices', ...email.notice },
    ];
  });

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    await this.action.run(async () => {
      this.data.set(await this.api.request<AdminOverview>('/v1/admin/overview'));
    });
  }

  hourSummary(hour: StatusHour): string {
    const when = this.format.timestamp(hour.start);
    if (!hour.runs) return `${when}: no record`;
    return `${when}: ${hour.collected} collected, ${hour.failed} failed`;
  }

  day(seconds: number): string {
    return this.format.day(seconds);
  }

  minutes(seconds: number): string {
    return seconds % 3600 ? `${Math.round(seconds / 60)} minutes` : `${seconds / 3600} hours`;
  }
}
