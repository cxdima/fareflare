import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { FormField, form, maxLength, minLength, required, submit } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { TelegramFacade } from '../core/telegram.facade';
import type { Page } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { SecretComponent } from './shared/secret.component';
import { TelegramConnectComponent } from './shared/telegram-connect.component';
import { PreferencesComponent } from './preferences.component';

type Grant = {
  id: string;
  client_name: string;
  created_at: number;
  expires_at: number;
  revoked: boolean;
};
const sectionIds = ['display', 'notifications', 'connections', 'security'] as const;
type Section = (typeof sectionIds)[number];

/** Reads `#settings?section=security`, the address password managers are sent to. */
function linkedSection(): Section {
  const requested = new URLSearchParams(location.hash.split('?')[1] ?? '').get('section');
  return sectionIds.find((id) => id === requested) ?? 'display';
}

@Component({
  selector: 'ff-settings',
  standalone: true,
  imports: [
    FormField,
    DialogComponent,
    PreferencesComponent,
    SecretComponent,
    TelegramConnectComponent,
  ],
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
  readonly section = signal<Section>(linkedSection());
  readonly session = inject(SessionFacade);
  readonly telegram = inject(TelegramFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  readonly grantAction = new ActionState();
  readonly deleteAction = new ActionState();
  readonly passwordAction = new ActionState();
  readonly codeAction = new ActionState();
  readonly grants = signal<Grant[]>([]);
  readonly revoking = signal<Grant | null>(null);
  readonly deleting = signal(false);
  readonly deletionModel = signal({ password: '' });
  readonly deletion = form(this.deletionModel, (path) => required(path.password));
  readonly passwordChanged = signal(false);
  readonly passwordModel = signal({ current: '', next: '' });
  readonly password = form(this.passwordModel, (path) => {
    required(path.current, { message: 'Enter your current password.' });
    required(path.next, { message: 'Enter a new password.' });
    minLength(path.next, 15, { message: 'Use at least 15 characters.' });
    maxLength(path.next, 128, { message: 'Use no more than 128 characters.' });
  });
  /** Asking for the password before a new recovery code replaces the old one. */
  readonly replacingCode = signal(false);
  readonly newCode = signal('');
  readonly codeModel = signal({ password: '' });
  readonly code = form(this.codeModel, (path) =>
    required(path.password, { message: 'Enter your password.' }),
  );

  ngOnInit(): void {
    void this.grantAction.run(() => this.loadGrants());
  }
  /** Keeps the chosen section in the address, so a reload or a shared link returns to it. */
  open(section: Section): void {
    this.section.set(section);
    history.replaceState(
      null,
      '',
      location.pathname + location.search + '#settings?section=' + section,
    );
  }
  passwordError(field: 'current' | 'next'): string {
    const state = this.password[field]();
    return state.touched() ? (state.errors()[0]?.message ?? '') : '';
  }
  async changePassword(event: Event): Promise<void> {
    event.preventDefault();
    this.passwordChanged.set(false);
    await submit(this.password, async () => {
      await this.passwordAction.run(async () => {
        const { current, next } = this.passwordModel();
        await this.api.request('/auth/password', {
          method: 'POST',
          body: { current_password: current, new_password: next },
        });
        this.password().reset({ current: '', next: '' });
        this.passwordChanged.set(true);
      });
    });
    this.password().errorSummary()[0]?.fieldTree().focusBoundControl();
  }
  closeCodeRequest(): void {
    this.replacingCode.set(false);
    this.code().reset({ password: '' });
    this.codeAction.error.set('');
  }
  async createCode(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.code, async () => {
      await this.codeAction.run(async () => {
        const result = await this.api.request<{ recovery_code: string }>('/auth/recovery-code', {
          method: 'POST',
          body: this.codeModel(),
        });
        this.closeCodeRequest();
        this.newCode.set(result.recovery_code);
      });
    });
  }
  private async loadGrants(): Promise<void> {
    this.grants.set(
      (await this.api.request<Page<Grant>>('/v1/oauth/grants')).items.filter(
        (grant) => !grant.revoked,
      ),
    );
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
        this.session.leave();
        await this.router.navigate(['/login']);
      });
    });
  }
}
