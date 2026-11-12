import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  inject,
  output,
  signal,
} from '@angular/core';
import { ApiService } from '../../core/api.service';
import { RegionalFormat } from '../../core/regional-format';
import type { AdminUserRow, AdminUsers } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { accountStatusLabels, accountStatusTone } from './admin-labels';

const PAGE = 50;

@Component({
  selector: 'ff-admin-users',
  standalone: true,
  templateUrl: './admin-users.component.html',
  styleUrls: ['./admin-table.scss', './admin-users.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminUsersComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  readonly format = inject(RegionalFormat);
  readonly choose = output<string>();
  readonly page = signal<AdminUsers | null>(null);
  readonly action = new ActionState();
  readonly query = signal('');
  readonly status = signal('all');
  readonly sort = signal('newest');
  readonly offset = signal(0);
  readonly statusLabels = accountStatusLabels;
  readonly statusTone = accountStatusTone;
  private typing: ReturnType<typeof setTimeout> | undefined;
  private request = 0;

  ngOnInit(): void {
    void this.load();
  }

  ngOnDestroy(): void {
    clearTimeout(this.typing);
  }

  search(value: string): void {
    this.query.set(value);
    clearTimeout(this.typing);
    // Each keystroke would scan every account; wait for a pause in typing.
    this.typing = setTimeout(() => {
      this.offset.set(0);
      void this.load();
    }, 250);
  }

  filter(status: string): void {
    this.status.set(status);
    this.offset.set(0);
    void this.load();
  }

  order(sort: string): void {
    this.sort.set(sort);
    this.offset.set(0);
    void this.load();
  }

  turn(step: number): void {
    this.offset.set(Math.max(0, this.offset() + step * PAGE));
    void this.load();
  }

  async load(): Promise<void> {
    const request = ++this.request;
    const params = new URLSearchParams({
      q: this.query().trim(),
      status: this.status(),
      sort: this.sort(),
      offset: String(this.offset()),
      limit: String(PAGE),
    });
    await this.action.run(async () => {
      const page = await this.api.request<AdminUsers>(`/v1/admin/users?${params}`);
      // Only the newest search may fill the table; an older, slower answer is dropped.
      if (request === this.request) this.page.set(page);
    });
  }

  open(event: Event, row: AdminUserRow): void {
    event.preventDefault();
    this.choose.emit(row.id);
  }

  signIn(row: AdminUserRow): string {
    const ways = [];
    if (row.passkeys) ways.push(row.passkeys === 1 ? 'Passkey' : `${row.passkeys} passkeys`);
    if (row.two_factor) ways.push('Two-step');
    return ways.length ? ways.join(' · ') : 'Password only';
  }
}
