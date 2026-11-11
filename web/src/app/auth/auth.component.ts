import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Title } from '@angular/platform-browser';
import { Router, ActivatedRoute } from '@angular/router';
import {
  FormField,
  applyWhen,
  form,
  maxLength,
  minLength,
  required,
  submit,
  validate,
} from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { message } from '../core/format';
import {
  getPasskey,
  passkeyAutofillSupported,
  passkeyCancelled,
  passkeysSupported,
} from '../core/passkey';
import { SessionFacade } from '../core/session.facade';
import type { AccountResponse, PasskeyOptions, TwoFactorChallenge } from '../core/types';
import { ActionState } from '../dashboard/shared/action-state';

type Mode = 'login' | 'register' | 'forgot' | 'reset' | 'confirm';

const paths: Record<string, Mode> = {
  login: 'login',
  register: 'register',
  'forgot-password': 'forgot',
  'reset-password': 'reset',
  'confirm-email': 'confirm',
};
const addresses: Record<Mode, string> = {
  login: '/login',
  register: '/register',
  forgot: '/forgot-password',
  reset: '/reset-password',
  confirm: '/confirm-email',
};
const titles: Record<Mode, string> = {
  login: 'Sign in',
  register: 'Create your account',
  forgot: 'Reset your password',
  reset: 'Choose a new password',
  confirm: 'Confirm your email',
};
// Kept in step with the service's own rule in accounts.py.
const email =
  /^[a-zA-Z0-9][a-zA-Z0-9._%+-]{0,63}@[a-zA-Z0-9][a-zA-Z0-9-]{0,62}(?:\.[a-zA-Z0-9][a-zA-Z0-9-]{0,62})*\.[a-zA-Z]{2,24}$/;

@Component({
  selector: 'ff-auth',
  standalone: true,
  imports: [FormField],
  templateUrl: './auth.component.html',
  styleUrl: './auth.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthComponent implements OnInit, OnDestroy {
  readonly session = inject(SessionFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly title = inject(Title);
  // Set while this page was reached by switching between the sign-in pages.
  private readonly carried = this.router.currentNavigation()?.extras.state as
    { username?: string; switched?: boolean } | undefined;
  readonly action = new ActionState();
  readonly mode = signal<Mode>('login');
  /** A password sign-in for an account with two-step sign-in asks for a code next. */
  readonly step = signal<'credentials' | 'code'>('credentials');
  readonly useBackupCode = signal(false);
  readonly passwordVisible = signal(false);
  readonly passkeys = passkeysSupported();
  /** The forgot-password page, after the link was requested. */
  readonly sent = signal('');
  /** The reset page: what the link is for, once it has been checked. */
  readonly reset = signal<{ email: string | null; two_factor: boolean } | null>(null);
  readonly linkProblem = signal('');
  readonly confirmed = signal('');
  readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  readonly codeInput = viewChild<ElementRef<HTMLInputElement>>('codeInput');
  private twoFactorToken = '';
  private linkToken = '';
  private autofill: AbortController | null = null;
  readonly model = signal({ username: this.carried?.username ?? '', password: '', code: '' });
  readonly needsEmail = computed(() => ['register', 'forgot'].includes(this.mode()));
  readonly credentials = form(this.model, (path) => {
    required(path.username, {
      when: () => ['login', 'register', 'forgot'].includes(this.mode()) && this.step() !== 'code',
      message: 'Enter your email address.',
    });
    maxLength(path.username, 254, { message: 'Use no more than 254 characters.' });
    applyWhen(
      path.username,
      () => this.needsEmail(),
      (field) =>
        validate(field, ({ value }) =>
          !value().trim() || email.test(value().trim())
            ? null
            : { kind: 'email', message: 'Enter an email address, like name@example.com.' },
        ),
    );
    required(path.password, {
      when: () => ['login', 'register', 'reset'].includes(this.mode()) && this.step() !== 'code',
      message: 'Enter your password.',
    });
    maxLength(path.password, 128, { message: 'Use no more than 128 characters.' });
    applyWhen(
      path.password,
      () => this.mode() === 'register' || this.mode() === 'reset',
      (p) => minLength(p, 15, { message: 'Use at least 15 characters.' }),
    );
    maxLength(path.code, 9, { message: 'A code has 6 digits, or 8 characters for a backup code.' });
    required(path.code, {
      when: () => this.step() === 'code' || (this.mode() === 'reset' && !!this.reset()?.two_factor),
      message: 'Enter the code.',
    });
  });

  async ngOnInit(): Promise<void> {
    this.mode.set(paths[this.route.snapshot.routeConfig?.path ?? 'login'] ?? 'login');
    this.title.setTitle(`${titles[this.mode()]} · Fareflare`);
    if (this.mode() === 'reset' || this.mode() === 'confirm') this.takeLinkToken();
    if (!this.session.ready()) await this.session.bootstrap();
    if (this.mode() === 'confirm') return void (await this.confirmEmail());
    if (this.mode() === 'reset') return void (await this.checkReset());
    if (this.session.account()) return void (await this.enterWorkspace());
    const params = this.route.snapshot.queryParamMap;
    // Older invitation and sign-up links open the sign-in address.
    const signingUp =
      this.mode() === 'login' &&
      !this.carried?.switched &&
      (params.has('invite') || params.get('mode') === 'register');
    if (signingUp) return void (await this.changeMode('register', true));
    if (this.mode() === 'register' && this.session.config()?.registration_mode === 'closed')
      return void (await this.changeMode('login', true));
    if (this.carried?.switched) this.focusHeading();
    if (this.mode() === 'login') void this.offerPasskeyAutofill();
  }

  ngOnDestroy(): void {
    this.autofill?.abort();
  }

  /** Each page has its own address, so the back button and password managers see a page. */
  async changeMode(mode: Mode, replaceUrl = false): Promise<void> {
    if (this.action.busy()) return;
    this.autofill?.abort();
    await this.router.navigate([addresses[mode]], {
      queryParams: this.forwarded(),
      // A workspace destination in the fragment survives; a link's token never does.
      preserveFragment:
        !['reset', 'confirm'].includes(mode) && !['reset', 'confirm'].includes(this.mode()),
      replaceUrl,
      state: { username: this.model().username, switched: true },
    });
  }

  async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.action.busy()) return;
    const step = this.step();
    await submit(this.credentials, async () => {
      await this.action.run(async () => {
        const mode = this.mode();
        if (this.step() === 'code') return this.submitCode();
        if (mode === 'forgot') return this.requestReset();
        if (mode === 'reset') return this.setNewPassword();
        this.autofill?.abort();
        const values = this.model();
        const result = await this.api.request<AccountResponse | TwoFactorChallenge>(
          `/auth/${mode}`,
          {
            method: 'POST',
            body:
              mode === 'register'
                ? { email: values.username.trim(), password: values.password }
                : { username: values.username.trim(), password: values.password },
          },
        );
        if ('two_factor_required' in result) {
          this.twoFactorToken = result.token;
          this.step.set('code');
          // A new, empty field: nothing about it has been wrong yet.
          this.credentials.code().reset();
          this.title.setTitle('Enter your code · Fareflare');
          requestAnimationFrame(() => this.codeInput()?.nativeElement.focus());
          return;
        }
        await this.signedIn(result);
      });
    });
    // Point at the first mistake, unless the page moved on to its next step.
    if (this.step() === step && !this.sent())
      this.credentials().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  /** Signs in with a passkey from the browser or password manager prompt. */
  async signInWithPasskey(): Promise<void> {
    this.autofill?.abort();
    await this.action.run(async () => {
      const request = await this.api.request<PasskeyOptions>('/auth/passkey/options', {
        method: 'POST',
      });
      let credential;
      try {
        credential = await getPasskey(request.options);
      } catch (error) {
        if (passkeyCancelled(error)) return;
        if (error instanceof DOMException && error.name === 'SecurityError')
          throw new Error('Passkeys work only when Fareflare is opened by its domain name.');
        throw error;
      }
      if (credential) await this.finishPasskey(request.challenge_id, credential);
    });
  }

  toggleBackupCode(): void {
    this.useBackupCode.update((value) => !value);
    this.model.update((model) => ({ ...model, code: '' }));
    requestAnimationFrame(() => this.codeInput()?.nativeElement.focus());
  }

  backToPassword(): void {
    this.step.set('credentials');
    this.twoFactorToken = '';
    this.useBackupCode.set(false);
    this.model.update((model) => ({ ...model, password: '', code: '' }));
    this.action.error.set('');
    this.title.setTitle(`${titles[this.mode()]} · Fareflare`);
  }

  fieldError(field: 'username' | 'password' | 'code'): string {
    const state = this.credentials[field]();
    return state.touched() ? (state.errors()[0]?.message ?? '') : '';
  }

  /** The passkey choice inside the email field's autofill list, where it is supported. */
  private async offerPasskeyAutofill(): Promise<void> {
    if (!(await passkeyAutofillSupported())) return;
    this.autofill = new AbortController();
    const signal = this.autofill.signal;
    try {
      const request = await this.api.request<PasskeyOptions>('/auth/passkey/options', {
        method: 'POST',
        signal,
      });
      const credential = await getPasskey(request.options, true, signal);
      if (credential && !signal.aborted)
        await this.action.run(() => this.finishPasskey(request.challenge_id, credential));
    } catch {
      // Autofill is a quiet extra: if the browser declines it, the button still works.
    }
  }

  private async finishPasskey(challengeId: string, credential: object): Promise<void> {
    const result = await this.api.request<AccountResponse>('/auth/passkey', {
      method: 'POST',
      body: { challenge_id: challengeId, credential },
    });
    await this.signedIn(result);
  }

  private async submitCode(): Promise<void> {
    const result = await this.api.request<AccountResponse>('/auth/login/two-factor', {
      method: 'POST',
      body: { token: this.twoFactorToken, code: this.model().code.trim() },
    });
    await this.signedIn(result);
  }

  private async requestReset(): Promise<void> {
    const address = this.model().username.trim();
    await this.api.request('/auth/password-reset', { method: 'POST', body: { email: address } });
    this.sent.set(address);
    this.focusHeading();
  }

  private async setNewPassword(): Promise<void> {
    const values = this.model();
    const result = await this.api.request<AccountResponse>('/auth/password-reset/confirm', {
      method: 'POST',
      body: {
        token: this.linkToken,
        new_password: values.password,
        ...(this.reset()?.two_factor ? { code: values.code.trim() } : {}),
      },
    });
    this.linkToken = '';
    await this.signedIn(result);
  }

  private async checkReset(): Promise<void> {
    if (!this.linkToken) return void this.linkProblem.set('This reset link is incomplete.');
    try {
      this.reset.set(
        await this.api.request('/auth/password-reset/check', {
          method: 'POST',
          body: { token: this.linkToken },
        }),
      );
    } catch (error) {
      this.linkProblem.set(message(error));
    }
  }

  private async confirmEmail(): Promise<void> {
    if (!this.linkToken) return void this.linkProblem.set('This confirmation link is incomplete.');
    try {
      const result = await this.api.request<{ email: string }>('/auth/email/confirm', {
        method: 'POST',
        body: { token: this.linkToken },
      });
      this.confirmed.set(result.email);
      const account = this.session.account();
      if (account?.email === result.email)
        this.session.account.set({ ...account, email_verified: true });
    } catch (error) {
      this.linkProblem.set(message(error));
    }
    this.focusHeading();
  }

  /** Reads a link's token from the address fragment, then takes it out of the address bar. */
  private takeLinkToken(): void {
    this.linkToken = new URLSearchParams(this.route.snapshot.fragment ?? '').get('token') ?? '';
    history.replaceState(history.state, '', location.pathname);
  }

  private async signedIn(result: AccountResponse): Promise<void> {
    this.session.accept(result);
    this.model.set({ username: '', password: '', code: '' });
    await this.enterWorkspace();
  }

  private focusHeading(): void {
    requestAnimationFrame(() => this.heading()?.nativeElement.focus());
  }

  /** What must survive a change of page: an application waiting for consent. */
  private forwarded(): Record<string, string> {
    const authorize = this.route.snapshot.queryParamMap.get('authorize');
    return authorize ? { authorize } : {};
  }

  async enterWorkspace(): Promise<void> {
    const authorize = this.route.snapshot.queryParamMap.get('authorize');
    const linked = this.mode() === 'reset' || this.mode() === 'confirm';
    await this.router.navigate(['/app'], {
      queryParams: authorize ? { authorize } : {},
      // Someone sent to sign in from a page of the workspace returns to that page.
      fragment: linked ? undefined : (this.route.snapshot.fragment ?? undefined),
      replaceUrl: true,
    });
  }
}
