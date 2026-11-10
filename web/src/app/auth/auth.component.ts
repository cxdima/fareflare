import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
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
import { SessionFacade } from '../core/session.facade';
import type { AccountResponse } from '../core/types';
import { ActionState } from '../dashboard/shared/action-state';
import { SecretComponent } from '../dashboard/shared/secret.component';

type Mode = 'login' | 'register' | 'recover';

// Kept in step with the service's own rule in accounts.py.
const username = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$/;
const email =
  /^[a-zA-Z0-9][a-zA-Z0-9._%+-]{0,63}@[a-zA-Z0-9][a-zA-Z0-9-]{0,62}(?:\.[a-zA-Z0-9][a-zA-Z0-9-]{0,62})*\.[a-zA-Z]{2,24}$/;
const titles: Record<Mode, string> = {
  login: 'Sign in',
  register: 'Create your account',
  recover: 'Recover your account',
};

@Component({
  selector: 'ff-auth',
  standalone: true,
  imports: [FormField, SecretComponent],
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
  // Set while this page was reached by switching between sign-in, sign-up and recovery.
  private readonly carried = this.router.currentNavigation()?.extras.state as
    { username?: string; switched?: boolean } | undefined;
  readonly action = new ActionState();
  readonly mode = signal<Mode>('login');
  /** After sign-up or recovery the new code is shown once, before the workspace opens. */
  readonly step = signal<'credentials' | 'recovery'>('credentials');
  readonly passwordVisible = signal(false);
  readonly heading = viewChild<ElementRef<HTMLElement>>('heading');
  readonly model = signal({
    username: this.carried?.username ?? '',
    password: '',
    invite: '',
    recoveryCode: '',
  });
  readonly credentials = form(this.model, (path) => {
    required(path.username, { message: 'Enter your email or username.' });
    maxLength(path.username, 254, { message: 'Use no more than 254 characters.' });
    applyWhen(
      path.username,
      () => this.mode() === 'register',
      (field) =>
        validate(field, ({ value }) => {
          const name = value().trim();
          return !name || username.test(name) || email.test(name)
            ? null
            : {
                kind: 'sign-in-name',
                message:
                  'Use an email address, or a username of 3–40 letters, numbers, periods, underscores or hyphens.',
              };
        }),
    );
    required(path.password, { message: 'Enter your password.' });
    maxLength(path.password, 128, { message: 'Use no more than 128 characters.' });
    applyWhen(
      path.password,
      () => this.mode() !== 'login',
      (p) => minLength(p, 15, { message: 'Use at least 15 characters.' }),
    );
    required(path.invite, {
      when: () =>
        this.mode() === 'register' && this.session.config()?.registration_mode === 'invite',
      message: 'Enter the invitation code from your link.',
    });
    required(path.recoveryCode, {
      when: () => this.mode() === 'recover',
      message: 'Enter the recovery code you saved when you signed up.',
    });
  });
  // Leaving before the code is saved would lose the only way to recover the account.
  private readonly warnBeforeLeaving = (event: BeforeUnloadEvent) => event.preventDefault();

  async ngOnInit(): Promise<void> {
    const params = this.route.snapshot.queryParamMap;
    const path = this.route.snapshot.routeConfig?.path;
    const invite = params.get('invite') ?? '';
    this.model.update((model) => ({ ...model, invite }));
    if (path === 'register' || path === 'recover') this.mode.set(path);
    this.title.setTitle(`${titles[this.mode()]} · Fareflare`);
    if (!this.session.ready()) await this.session.bootstrap();
    if (this.session.account()) return void (await this.enterWorkspace());
    // Older invitation and sign-up links open the sign-in address.
    const signingUp =
      this.mode() === 'login' &&
      !this.carried?.switched &&
      (invite || params.get('mode') === 'register');
    if (signingUp) return void (await this.changeMode('register', true));
    if (this.mode() === 'register' && this.session.config()?.registration_mode === 'closed')
      return void (await this.changeMode('login', true));
    if (this.carried?.switched) this.focusHeading();
  }

  ngOnDestroy(): void {
    window.removeEventListener('beforeunload', this.warnBeforeLeaving);
  }

  /** Each mode has its own address, so the back button and password managers see a page. */
  async changeMode(mode: Mode, replaceUrl = false): Promise<void> {
    if (this.action.busy()) return;
    await this.router.navigate(['/' + mode], {
      queryParams: this.forwarded(),
      preserveFragment: true,
      replaceUrl,
      state: { username: this.model().username, switched: true },
    });
  }

  async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.action.busy()) return;
    await submit(this.credentials, async () => {
      await this.action.run(async () => {
        const values = this.model();
        const mode = this.mode();
        const name = values.username.trim();
        const body =
          mode === 'recover'
            ? {
                username: name,
                recovery_code: values.recoveryCode.trim(),
                new_password: values.password,
              }
            : {
                username: name,
                password: values.password,
                ...(mode === 'register' && values.invite ? { invite_token: values.invite } : {}),
              };
        const result = await this.api.request<AccountResponse>(`/auth/${mode}`, {
          method: 'POST',
          body,
        });
        this.session.accept(result);
        this.model.set({ username: '', password: '', invite: '', recoveryCode: '' });
        if (!this.session.recovery()) return void (await this.enterWorkspace());
        this.step.set('recovery');
        this.title.setTitle('Save your recovery code · Fareflare');
        window.addEventListener('beforeunload', this.warnBeforeLeaving);
        this.focusHeading();
      });
    });
    this.credentials().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  async finish(): Promise<void> {
    window.removeEventListener('beforeunload', this.warnBeforeLeaving);
    this.session.recovery.set('');
    await this.enterWorkspace();
  }

  fieldError(field: 'username' | 'password' | 'invite' | 'recoveryCode'): string {
    const state = this.credentials[field]();
    return state.touched() ? (state.errors()[0]?.message ?? '') : '';
  }

  private focusHeading(): void {
    requestAnimationFrame(() => this.heading()?.nativeElement.focus());
  }

  /** What must survive a change of mode: an invitation, or an application waiting for consent. */
  private forwarded(): Record<string, string> {
    const params = this.route.snapshot.queryParamMap;
    const kept: Record<string, string> = {};
    for (const name of ['invite', 'authorize']) {
      const value = params.get(name);
      if (value) kept[name] = value;
    }
    return kept;
  }

  private async enterWorkspace(): Promise<void> {
    const authorize = this.route.snapshot.queryParamMap.get('authorize');
    await this.router.navigate(['/app'], {
      queryParams: authorize ? { authorize } : {},
      // Someone sent to sign in from a page of the workspace returns to that page.
      fragment: this.route.snapshot.fragment ?? undefined,
      replaceUrl: true,
    });
  }
}
