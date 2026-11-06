import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { FormField, form, required, submit } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import type { Page } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { PreferencesComponent } from './preferences.component';

type Telegram = { enabled: boolean; connected: boolean; bot_username?: string };
type Grant = {
  id: string;
  client_name: string;
  created_at: number;
  expires_at: number;
  revoked: boolean;
};

@Component({
  selector: 'ff-settings',
  standalone: true,
  imports: [FormField, DialogComponent, PreferencesComponent],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsComponent implements OnInit {
  readonly sections = [
    { id: 'display', label: 'Display', icon: 'bi-globe2' },
    { id: 'notifications', label: 'Notifications', icon: 'bi-bell' },
    { id: 'connections', label: 'Connections', icon: 'bi-link-45deg' },
    { id: 'security', label: 'Security', icon: 'bi-shield-check' },
  ] as const;
  readonly section = signal<'display' | 'notifications' | 'connections' | 'security'>('display');
  readonly session = inject(SessionFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly telegramAction = new ActionState();
  readonly grantAction = new ActionState();
  readonly deleteAction = new ActionState();
  readonly telegram = signal<Telegram | null>(null);
  readonly telegramUrl = signal('');
  readonly grants = signal<Grant[]>([]);
  readonly revoking = signal<Grant | null>(null);
  readonly deleting = signal(false);
  readonly deletionModel = signal({ password: '' });
  readonly deletion = form(this.deletionModel, (path) => required(path.password));

  ngOnInit(): void {
    void this.telegramAction.run(() => this.loadTelegram());
    void this.grantAction.run(() => this.loadGrants());
  }
  private async loadTelegram(): Promise<void> {
    const value = await this.api.request<Telegram>('/v1/telegram');
    this.telegram.set(value);
    if (value.connected) this.telegramUrl.set('');
  }
  private async loadGrants(): Promise<void> {
    this.grants.set(
      (await this.api.request<Page<Grant>>('/v1/oauth/grants')).items.filter(
        (grant) => !grant.revoked,
      ),
    );
  }
  async connectTelegram(): Promise<void> {
    await this.telegramAction.run(async () => {
      const result = await this.api.request<{ url: string }>('/v1/telegram', { method: 'POST' });
      const url = new URL(result.url);
      if (url.protocol !== 'https:' || url.hostname !== 't.me')
        throw new Error('The server returned an invalid Telegram link.');
      this.telegramUrl.set(url.href);
    });
  }
  async checkTelegram(): Promise<void> {
    await this.telegramAction.run(() => this.loadTelegram());
  }
  async disconnectTelegram(): Promise<void> {
    await this.telegramAction.run(async () => {
      await this.api.request('/v1/telegram', { method: 'DELETE' });
      this.telegramUrl.set('');
      await this.loadTelegram();
    });
  }
  async revoke(grant: Grant): Promise<void> {
    await this.grantAction.run(async () => {
      await this.api.request(`/v1/oauth/grants/${grant.id}`, { method: 'DELETE' });
      this.revoking.set(null);
      await this.loadGrants();
    });
  }
  closeDeletion(): void {
    this.deleting.set(false);
    this.deletionModel.set({ password: '' });
    this.deleteAction.error.set('');
  }
  async remove(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.deletion, async () => {
      await this.deleteAction.run(async () => {
        await this.api.request('/v1/account', { method: 'DELETE', body: this.deletionModel() });
        this.deletionModel.set({ password: '' });
        this.session.clear();
        await this.router.navigate(['/login']);
      });
    });
  }
}
