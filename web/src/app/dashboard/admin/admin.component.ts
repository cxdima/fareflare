import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { ApiService } from '../../core/api.service';
import { RegionalFormat } from '../../core/regional-format';
import { SessionFacade } from '../../core/session.facade';
import type { AdminGate } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { AdminActivityComponent } from './admin-activity.component';
import { AdminControlsComponent } from './admin-controls.component';
import { AdminFlightsComponent } from './admin-flights.component';
import { AdminOverviewComponent } from './admin-overview.component';
import { AdminUserComponent } from './admin-user.component';
import { AdminUsersComponent } from './admin-users.component';

const tabs = [
  { id: 'overview', label: 'Overview', icon: 'bi-grid-1x2' },
  { id: 'users', label: 'Users', icon: 'bi-people' },
  { id: 'flights', label: 'Flights', icon: 'bi-airplane' },
  { id: 'activity', label: 'Activity', icon: 'bi-journal-text' },
  { id: 'controls', label: 'Controls', icon: 'bi-toggles' },
] as const;
export type AdminTab = (typeof tabs)[number]['id'];

/** Reads `#admin?tab=users&user=acct_…`, so a reload or a shared link returns to the place. */
function readAddress(): { tab: AdminTab; user: string | null } {
  const params = new URLSearchParams(location.hash.split('?')[1] ?? '');
  const requested = params.get('user');
  const user = requested && /^acct_[a-f0-9]{32}$/.test(requested) ? requested : null;
  const tab = tabs.find((item) => item.id === params.get('tab'))?.id ?? 'overview';
  return { tab: user ? 'users' : tab, user };
}

/** The operator's view of the whole service. It opens only after the server says so. */
@Component({
  selector: 'ff-admin',
  standalone: true,
  imports: [
    AdminOverviewComponent,
    AdminUsersComponent,
    AdminUserComponent,
    AdminFlightsComponent,
    AdminActivityComponent,
    AdminControlsComponent,
  ],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly session = inject(SessionFacade);
  readonly format = inject(RegionalFormat);
  readonly tabs = tabs;
  readonly gate = signal<AdminGate | null>(null);
  readonly loading = new ActionState();
  readonly leaving = new ActionState();
  readonly tab = signal<AdminTab>(readAddress().tab);
  readonly user = signal<string | null>(readAddress().user);
  private readonly sync = () => {
    const address = readAddress();
    this.tab.set(address.tab);
    this.user.set(address.user);
  };

  async ngOnInit(): Promise<void> {
    window.addEventListener('hashchange', this.sync);
    await this.loading.run(async () => {
      this.gate.set(await this.api.request<AdminGate>('/v1/admin/gate'));
    });
  }

  ngOnDestroy(): void {
    window.removeEventListener('hashchange', this.sync);
  }

  open(tab: AdminTab): void {
    this.go({ tab }, false);
  }

  /** A person's page is its own history entry, so Back returns to the list. */
  openUser(id: string): void {
    this.go({ tab: 'users', user: id }, true);
  }

  closeUser(): void {
    this.go({ tab: 'users' }, false);
  }

  private go(params: Record<string, string>, push: boolean): void {
    const url = `${location.pathname}${location.search}#admin?${new URLSearchParams(params)}`;
    if (push) history.pushState(null, '', url);
    else history.replaceState(null, '', url);
    this.sync();
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }

  /**
   * Ends this session without calling it a deliberate sign-out, so the workspace sends
   * the person to sign in with this page kept in the address, and returns them here.
   */
  async signInAgain(): Promise<void> {
    await this.leaving.run(async () => {
      await this.api.request('/auth/logout', { method: 'POST' });
      this.session.clear();
    });
  }
}
