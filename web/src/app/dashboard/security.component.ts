import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DomSanitizer, SafeUrl } from '@angular/platform-browser';
import { Router } from '@angular/router';
import {
  FormField,
  form,
  maxLength,
  minLength,
  pattern,
  required,
  submit,
} from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { createPasskey, passkeyCancelled, passkeysSupported } from '../core/passkey';
import { SessionFacade } from '../core/session.facade';
import type { AccountResponse, Passkey, PasskeyOptions, Security } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { QrCodeComponent } from './shared/qr-code.component';

type Drawer =
  '' | 'email' | 'password' | 'passkey' | 'two-factor' | 'backup-codes' | 'turn-off' | 'sign-out';
type Setup = { secret: string; uri: string; account: string; issuer: string };

const emailRule =
  /^[a-zA-Z0-9][a-zA-Z0-9._%+-]{0,63}@[a-zA-Z0-9][a-zA-Z0-9-]{0,62}(?:\.[a-zA-Z0-9][a-zA-Z0-9-]{0,62})*\.[a-zA-Z]{2,24}$/;

/** Everything about getting into the account, in the order people look for it. */
@Component({
  selector: 'ff-security',
  standalone: true,
  imports: [FormField, DialogComponent, QrCodeComponent],
  templateUrl: './security.component.html',
  styleUrl: './security.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecurityComponent implements OnInit {
  readonly session = inject(SessionFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  readonly passkeysSupported = passkeysSupported();
  readonly state = signal<Security | null>(null);
  readonly loading = new ActionState();
  readonly open = signal<Drawer>('');
  readonly note = signal('');
  private readonly dates = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' });

  // Email
  readonly emailAction = new ActionState();
  readonly resendAction = new ActionState();
  readonly resent = signal(false);
  readonly emailModel = signal({ email: '', password: '' });
  readonly emailForm = form(this.emailModel, (path) => {
    required(path.email, { message: 'Enter an email address.' });
    pattern(path.email, emailRule, { message: 'Enter an email address, like name@example.com.' });
    required(path.password, { message: 'Enter your password.' });
  });

  // Password
  readonly passwordAction = new ActionState();
  readonly passwordModel = signal({ current: '', next: '' });
  readonly passwordForm = form(this.passwordModel, (path) => {
    required(path.current, { message: 'Enter your current password.' });
    required(path.next, { message: 'Enter a new password.' });
    minLength(path.next, 8, { message: 'Use at least 8 characters.' });
    maxLength(path.next, 128, { message: 'Use no more than 128 characters.' });
  });

  // Passkeys
  readonly passkeyAction = new ActionState();
  // A passkey signs in on its own, so adding one asks for the password first.
  readonly passkeyModel = signal({ password: '' });
  readonly passkeyForm = form(this.passkeyModel, (path) =>
    required(path.password, { message: 'Enter your password.' }),
  );
  readonly renaming = signal('');
  readonly renameModel = signal({ name: '' });
  readonly renameForm = form(this.renameModel, (path) => {
    required(path.name, { message: 'Enter a name.' });
    maxLength(path.name, 60, { message: 'Use no more than 60 characters.' });
  });
  readonly removing = signal<Passkey | null>(null);

  // Two-step sign-in
  readonly setupAction = new ActionState();
  readonly setup = signal<Setup | null>(null);
  readonly backupCodes = signal<string[]>([]);
  readonly copied = signal('');
  readonly setupModel = signal({ password: '', code: '' });
  readonly setupForm = form(this.setupModel, (path) => {
    required(path.password, {
      when: () => !this.setup(),
      message: 'Enter your password.',
    });
    required(path.code, { when: () => !!this.setup(), message: 'Enter the 6-digit code.' });
  });
  readonly codeAction = new ActionState();
  readonly codeModel = signal({ password: '', code: '' });
  readonly codeForm = form(this.codeModel, (path) => {
    required(path.password, { message: 'Enter your password.' });
    required(path.code, { message: 'Enter a code from your app, or a backup code.' });
  });
  readonly groupedSecret = computed(
    () =>
      this.setup()
        ?.secret.match(/.{1,4}/g)
        ?.join(' ') ?? '',
  );
  readonly appLink = computed<SafeUrl | null>(() => {
    const setup = this.setup();
    // An otpauth: link is built by the service from its own values, never from input.
    return setup ? this.sanitizer.bypassSecurityTrustUrl(setup.uri) : null;
  });

  // Sign out everywhere, and deletion
  readonly signOutAction = new ActionState();
  readonly signOutModel = signal({ password: '' });
  readonly signOutForm = form(this.signOutModel, (path) =>
    required(path.password, { message: 'Enter your password.' }),
  );
  readonly deleting = signal(false);
  readonly deleteAction = new ActionState();
  readonly deletionModel = signal({ password: '' });
  readonly deletion = form(this.deletionModel, (path) => required(path.password));

  ngOnInit(): void {
    void this.loading.run(() => this.reload());
  }

  date(seconds: number | null | undefined): string {
    return seconds ? this.dates.format(new Date(seconds * 1000)) : '';
  }

  toggle(drawer: Drawer): void {
    this.open.set(this.open() === drawer ? '' : drawer);
    this.note.set('');
    for (const action of [
      this.emailAction,
      this.passwordAction,
      this.passkeyAction,
      this.setupAction,
      this.codeAction,
    ])
      action.error.set('');
    if (drawer !== 'two-factor') this.setup.set(null);
    // reset() also forgets which fields were touched, so a closed drawer shows no errors.
    this.emailForm().reset({ email: this.state()?.email ?? '', password: '' });
    this.passwordForm().reset({ current: '', next: '' });
    this.passkeyForm().reset({ password: '' });
    this.setupForm().reset({ password: '', code: '' });
    this.codeForm().reset({ password: '', code: '' });
    this.signOutForm().reset({ password: '' });
  }

  error(field: { touched: () => boolean; errors: () => { message?: string }[] }): string {
    return field.touched() ? (field.errors()[0]?.message ?? '') : '';
  }

  async changeEmail(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.emailForm, async () => {
      await this.emailAction.run(async () => {
        const result = await this.api.request<{ account: AccountResponse['account'] }>(
          '/auth/email',
          { method: 'POST', body: this.emailModel() },
        );
        this.session.account.set(result.account);
        await this.reload();
        this.toggle('');
        this.note.set(
          this.state()?.email_enabled
            ? `We sent a confirmation link to ${result.account.email}.`
            : 'Email address saved.',
        );
      });
    });
  }

  async resend(): Promise<void> {
    this.resent.set(false);
    await this.resendAction.run(async () => {
      await this.api.request('/auth/email/resend', { method: 'POST' });
      this.resent.set(true);
    });
  }

  async changePassword(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.passwordForm, async () => {
      await this.passwordAction.run(async () => {
        const { current, next } = this.passwordModel();
        await this.api.request('/auth/password', {
          method: 'POST',
          body: { current_password: current, new_password: next },
        });
        this.toggle('');
        this.note.set(
          'Password changed and your other browsers signed out. Update it in your password manager if it did not offer to.',
        );
      });
    });
    // Only while the drawer is still open: after a change it closes, and its empty
    // fields must not be focused (and so marked touched) on the way out.
    if (this.open() === 'password')
      this.passwordForm().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  async addPasskey(event: Event): Promise<void> {
    event.preventDefault();
    this.note.set('');
    await submit(this.passkeyForm, () => this.createPasskey());
    if (this.open() === 'passkey')
      this.passkeyForm().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  private async createPasskey(): Promise<void> {
    await this.passkeyAction.run(async () => {
      const request = await this.api.request<PasskeyOptions>('/auth/passkeys/options', {
        method: 'POST',
        body: this.passkeyModel(),
      });
      let credential;
      try {
        credential = await createPasskey(request.options);
      } catch (error) {
        if (error instanceof DOMException && error.name === 'InvalidStateError')
          throw new Error('That passkey is already on your account.');
        if (error instanceof DOMException && error.name === 'SecurityError')
          throw new Error('Passkeys work only when Fareflare is opened by its domain name.');
        if (passkeyCancelled(error)) return;
        throw error;
      }
      const added = await this.api.request<Passkey>('/auth/passkeys', {
        method: 'POST',
        body: { challenge_id: request.challenge_id, credential },
      });
      await this.reload();
      this.toggle('');
      this.note.set(
        `Passkey added: ${added.name}. Next time, sign in with it instead of a password.`,
      );
    });
  }

  startRename(passkey: Passkey): void {
    this.renaming.set(passkey.id);
    this.renameModel.set({ name: passkey.name });
  }

  async rename(event: Event, passkey: Passkey): Promise<void> {
    event.preventDefault();
    await submit(this.renameForm, async () => {
      await this.passkeyAction.run(async () => {
        await this.api.request(`/auth/passkeys/${passkey.id}`, {
          method: 'PATCH',
          body: { name: this.renameModel().name.trim() },
        });
        this.renaming.set('');
        await this.reload();
      });
    });
  }

  async remove(passkey: Passkey): Promise<void> {
    await this.passkeyAction.run(async () => {
      await this.api.request(`/auth/passkeys/${passkey.id}`, { method: 'DELETE' });
      this.removing.set(null);
      await this.reload();
      this.note.set(`Passkey removed: ${passkey.name}. Delete it from your password manager too.`);
    });
  }

  async continueSetup(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.setupForm, async () => {
      await this.setupAction.run(async () => {
        const values = this.setupModel();
        if (!this.setup()) {
          this.setup.set(
            await this.api.request<Setup>('/auth/two-factor/setup', {
              method: 'POST',
              body: { password: values.password },
            }),
          );
          this.setupForm().reset({ password: '', code: '' });
          return;
        }
        const result = await this.api.request<{ backup_codes: string[] }>(
          '/auth/two-factor/enable',
          { method: 'POST', body: { code: values.code.trim() } },
        );
        this.toggle('');
        this.backupCodes.set(result.backup_codes);
        await this.reload();
        this.focusCodes();
      });
    });
  }

  /** The codes replace the form that was in focus, so focus moves to them. */
  private focusCodes(): void {
    requestAnimationFrame(() => document.getElementById('backup-title')?.focus());
  }

  async changeTwoFactor(event: Event, kind: 'backup-codes' | 'turn-off'): Promise<void> {
    event.preventDefault();
    await submit(this.codeForm, async () => {
      await this.codeAction.run(async () => {
        const body = { password: this.codeModel().password, code: this.codeModel().code.trim() };
        if (kind === 'turn-off') {
          await this.api.request('/auth/two-factor/disable', { method: 'POST', body });
          this.toggle('');
          this.note.set('Two-step sign-in is off. Remove the Fareflare code from your app.');
        } else {
          const result = await this.api.request<{ backup_codes: string[] }>(
            '/auth/two-factor/backup-codes',
            { method: 'POST', body },
          );
          this.toggle('');
          this.backupCodes.set(result.backup_codes);
          this.focusCodes();
        }
        await this.reload();
      });
    });
  }

  async copy(text: string, what: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      this.copied.set(what);
      setTimeout(() => this.copied.set(''), 2400);
    } catch {
      this.copied.set('');
    }
  }

  downloadCodes(): void {
    const text = [
      'Fareflare backup codes',
      this.session.account()?.email ?? this.session.account()?.username ?? '',
      '',
      ...this.backupCodes(),
      '',
      'Each code works once, in place of a code from your authenticator app.',
    ].join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    link.download = 'fareflare-backup-codes.txt';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  async signOutEverywhere(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.signOutForm, async () => {
      await this.signOutAction.run(async () => {
        const result = await this.api.request<AccountResponse>('/auth/sign-out-everywhere', {
          method: 'POST',
          body: this.signOutModel(),
        });
        this.session.accept(result);
        this.toggle('');
        this.note.set(
          'Every other browser is signed out, and API keys, connected applications and Telegram were disconnected.',
        );
      });
    });
  }

  closeDeletion(): void {
    this.deleting.set(false);
    this.deletionModel.set({ password: '' });
    this.deleteAction.error.set('');
  }

  async deleteAccount(event: Event): Promise<void> {
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

  private async reload(): Promise<void> {
    const state = await this.api.request<Security>('/v1/account/security');
    this.state.set(state);
    const account = this.session.account();
    if (account)
      this.session.account.set({
        ...account,
        email: state.email,
        email_verified: state.email_verified,
      });
  }
}
