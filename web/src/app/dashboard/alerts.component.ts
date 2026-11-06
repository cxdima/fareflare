import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { RegionalFormat } from '../core/regional-format';
import type { Alert, Page } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { reasonLabel, routeName, statusLabel } from './shared/presentation';

@Component({
  selector: 'ff-alerts',
  standalone: true,
  templateUrl: './alerts.component.html',
  styleUrl: './alerts.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AlertsComponent implements OnInit {
  readonly workspace = inject(WorkspaceFacade);
  private readonly api = inject(ApiService);
  readonly action = new ActionState();
  readonly items = signal<Alert[]>([]);
  readonly cursor = signal<string | null>(null);
  readonly money = (amount: number, currency: string) => this.regional.money(amount, currency);
  readonly regional = inject(RegionalFormat);
  readonly timestamp = this.regional.timestamp;
  readonly reasonLabel = reasonLabel;
  readonly statusLabel = statusLabel;
  ngOnInit(): void {
    void this.load();
  }
  route(id: string): string {
    const monitor = this.workspace.monitors().find((item) => item.id === id);
    return monitor ? routeName(monitor) : 'Flight monitor';
  }
  async load(next?: string): Promise<void> {
    await this.action.run(() => this.fetch(next));
  }
  private async fetch(next?: string): Promise<void> {
    const page = await this.api.request<Page<Alert>>(
      '/v1/alerts' + (next ? '?cursor=' + encodeURIComponent(next) : ''),
    );
    this.items.update((previous) => (next ? [...previous, ...page.items] : page.items));
    this.cursor.set(page.next_cursor ?? null);
  }
  async retry(item: Alert): Promise<void> {
    await this.action.run(async () => {
      await this.api.request(`/v1/alerts/${item.id}/retry`, { method: 'POST' });
      await this.fetch();
    });
  }
}
