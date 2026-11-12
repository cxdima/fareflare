import { ChangeDetectionStrategy, Component, OnInit, inject, output, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { RegionalFormat } from '../../core/regional-format';
import type { AuditEntry, Page } from '../../core/types';
import { ActionState } from '../shared/action-state';
import { actionLabels, auditDetail } from './admin-labels';

/** Every admin action, newest first. The panel can read this record, never change it. */
@Component({
  selector: 'ff-admin-activity',
  standalone: true,
  templateUrl: './admin-activity.component.html',
  styleUrls: ['./admin-table.scss', './admin-activity.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminActivityComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly format = inject(RegionalFormat);
  readonly choose = output<string>();
  readonly items = signal<AuditEntry[]>([]);
  readonly cursor = signal<string | null>(null);
  readonly loaded = signal(false);
  readonly action = new ActionState();
  readonly actionLabels = actionLabels;
  readonly auditDetail = auditDetail;

  ngOnInit(): void {
    void this.load(false);
  }

  async load(more: boolean): Promise<void> {
    await this.action.run(async () => {
      const params = new URLSearchParams({ limit: '50' });
      const cursor = this.cursor();
      if (more && cursor) params.set('cursor', cursor);
      const page = await this.api.request<Page<AuditEntry>>(`/v1/admin/audit?${params}`);
      this.items.set(more ? [...this.items(), ...page.items] : page.items);
      this.cursor.set(page.next_cursor ?? null);
      this.loaded.set(true);
    });
  }

  open(event: Event, account: string): void {
    event.preventDefault();
    this.choose.emit(account);
  }
}
