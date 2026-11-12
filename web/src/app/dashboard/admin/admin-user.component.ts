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
import { ApiService } from '../../core/api.service';
import { RegionalFormat } from '../../core/regional-format';
import { SessionFacade } from '../../core/session.facade';
import type { AdminUser, Monitor } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { DialogComponent } from '../shared/dialog.component';
import { reasonLabel, statusLabel } from '../shared/presentation';
import {
  accountStatusLabels,
  accountStatusTone,
  actionLabels,
  auditDetail,
  routeOf,
  tripShape,
} from './admin-labels';

type AccountAction =
  'sign-out' | 'reset-two-factor' | 'temporary-password' | 'suspend' | 'reactivate' | 'delete';

/** What each action does, said before it is confirmed. */
const consequences: Record<AccountAction, { title: string; body: string; button: string }> = {
  'sign-out': {
    title: 'Sign this account out everywhere?',
    body: 'Every browser, API key, connected application and the Telegram link stop working. The person can sign in again.',
    button: 'Sign out everywhere',
  },
  'reset-two-factor': {
    title: 'Turn off two-step sign-in?',
    body: 'For someone who lost their authenticator and backup codes. Their password alone will sign in until they turn it back on. Their confirmed address is told.',
    button: 'Turn off two-step sign-in',
  },
  'temporary-password': {
    title: 'Issue a temporary password?',
    body: 'The current password stops working and every browser is signed out. You will see the temporary password once; it lasts 24 hours and must be replaced at the next sign-in.',
    button: 'Issue temporary password',
  },
  suspend: {
    title: 'Suspend this account?',
    body: 'The person is signed out everywhere and cannot sign in or receive alerts. Their flights are kept, so reactivating restores them.',
    button: 'Suspend account',
  },
  reactivate: {
    title: 'Reactivate this account?',
    body: 'The person can sign in again and their flights resume alerting. Their old sessions and API keys stay revoked.',
    button: 'Reactivate account',
  },
  delete: {
    title: 'Delete this account?',
    body: 'Sign-in, flights, API keys, connected applications and Telegram end for good. This cannot be undone.',
    button: 'Delete account',
  },
};

@Component({
  selector: 'ff-admin-user',
  standalone: true,
  imports: [DialogComponent],
  templateUrl: './admin-user.component.html',
  styleUrls: ['./admin-table.scss', './admin-user.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminUserComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly session = inject(SessionFacade);
  readonly format = inject(RegionalFormat);
  readonly id = input.required<string>();
  readonly back = output<void>();
  readonly data = signal<AdminUser | null>(null);
  readonly loading = new ActionState();
  readonly flightAction = new ActionState();
  readonly accountAction = new ActionState();
  readonly asking = signal<AccountAction | null>(null);
  readonly stopping = signal<Monitor | null>(null);
  readonly reason = signal('');
  readonly confirmText = signal('');
  readonly issued = signal<{ temporary_password: string; expires_at: number } | null>(null);
  readonly copied = signal(false);
  readonly note = signal('');
  readonly consequences = consequences;
  readonly statusLabels = accountStatusLabels;
  readonly statusTone = accountStatusTone;
  readonly actionLabels = actionLabels;
  readonly auditDetail = auditDetail;
  readonly routeOf = routeOf;
  readonly tripShape = tripShape;
  readonly statusLabel = statusLabel;
  readonly reasonLabel = reasonLabel;

  readonly own = computed(() => this.data()?.account.id === this.session.account()?.id);
  /** Admins and your own account are changed elsewhere: the command line, or your settings. */
  readonly actionable = computed(() => {
    const account = this.data()?.account;
    return !!account && !account.admin && !this.own() && account.status !== 'deleted';
  });
  readonly routes = computed(() => {
    const names = new Map<string, string>();
    for (const flight of this.data()?.flights ?? []) names.set(flight.id, routeOf(flight.target));
    return names;
  });

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    await this.loading.run(async () => {
      this.data.set(await this.api.request<AdminUser>(`/v1/admin/users/${this.id()}`));
    });
  }

  ask(action: AccountAction): void {
    this.reason.set('');
    this.confirmText.set('');
    this.accountAction.error.set('');
    this.asking.set(action);
  }

  async confirm(event: Event): Promise<void> {
    event.preventDefault();
    const action = this.asking();
    if (!action) return;
    await this.accountAction.run(async () => {
      if (action === 'delete') {
        await this.api.request(`/v1/admin/users/${this.id()}`, {
          method: 'DELETE',
          body: { confirm: this.confirmText(), reason: this.reason() },
        });
      } else {
        const result = await this.api.request<{
          temporary_password?: string;
          expires_at?: number;
        }>(`/v1/admin/users/${this.id()}/${action}`, {
          method: 'POST',
          body: { reason: this.reason() },
        });
        if (result.temporary_password && result.expires_at)
          this.issued.set({
            temporary_password: result.temporary_password,
            expires_at: result.expires_at,
          });
      }
      this.asking.set(null);
      this.note.set(actionLabels[action] + '.');
      await this.load();
    });
  }

  async setFlight(flight: Monitor, status: 'paused' | 'active' | 'cancelled'): Promise<void> {
    await this.flightAction.run(async () => {
      await this.api.request(`/v1/admin/users/${this.id()}/flights/${flight.id}`, {
        method: 'PATCH',
        body: { status, reason: status === 'cancelled' ? this.reason() : '' },
      });
      this.stopping.set(null);
      this.note.set(
        `${routeOf(flight.target)} ${status === 'paused' ? 'paused' : status === 'active' ? 'resumed' : 'stopped'}.`,
      );
      await this.load();
    });
  }

  askStop(flight: Monitor): void {
    this.reason.set('');
    this.flightAction.error.set('');
    this.stopping.set(flight);
  }

  async stop(event: Event): Promise<void> {
    event.preventDefault();
    const flight = this.stopping();
    if (flight) await this.setFlight(flight, 'cancelled');
  }

  async copy(value: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(value);
      this.copied.set(true);
    } catch {
      this.copied.set(false);
    }
  }

  closeIssued(): void {
    // The password is shown once: forget it as soon as the dialog closes.
    this.issued.set(null);
    this.copied.set(false);
  }

  price(flight: Monitor): string {
    return flight.latest
      ? this.format.money(flight.latest.amount_minor, flight.latest.currency)
      : '–';
  }

  money(amount: number | null, currency: string | null): string {
    return amount !== null && currency ? this.format.money(amount, currency) : '–';
  }

  canPause(flight: Monitor): boolean {
    return ['pending', 'active', 'degraded'].includes(flight.status);
  }

  canStop(flight: Monitor): boolean {
    return !['cancelled', 'expired'].includes(flight.status);
  }

  hookLabel(status: string): string {
    return { active: 'Verified', pending: 'Not verified', disabled: 'Disabled' }[status] ?? status;
  }

  needsReason(action: AccountAction): boolean {
    return action === 'suspend' || action === 'delete';
  }
}
