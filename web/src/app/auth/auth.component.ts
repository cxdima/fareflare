import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import {
  FormField,
  applyWhen,
  form,
  maxLength,
  minLength,
  pattern,
  required,
  submit,
} from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import type { AccountResponse } from '../core/types';
import { ActionState } from '../dashboard/shared/action-state';

@Component({
  selector: 'ff-auth',
  standalone: true,
  imports: [FormField],
  templateUrl: './auth.component.html',
  styleUrl: './auth.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthComponent implements OnInit {
  readonly session = inject(SessionFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  readonly action = new ActionState();
  readonly mode = signal<'login' | 'register' | 'recover'>('login');
  readonly passwordVisible = signal(false);
  readonly model = signal({ username: '', password: '', invite: '', recoveryCode: '' });
  readonly credentials = form(this.model, (path) => {
    required(path.username, { message: 'Enter your username.' });
    pattern(path.username, /^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}$/, {
      message:
        'Use 3–40 letters, numbers, periods, underscores or hyphens. Start with a letter or number.',
    });
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

  async ngOnInit(): Promise<void> {
    const params = this.route.snapshot.queryParamMap;
    const invite = params.get('invite') ?? '';
    this.model.update((model) => ({ ...model, invite }));
    if (
      invite ||
      params.get('mode') === 'register' ||
      this.route.snapshot.routeConfig?.path === 'register'
    )
      this.mode.set('register');
    if (this.route.snapshot.routeConfig?.path === 'recover') this.mode.set('recover');
    if (!this.session.ready()) await this.session.bootstrap();
    if (this.session.account()) await this.enterWorkspace();
  }

  changeMode(mode: 'login' | 'register' | 'recover'): void {
    if (this.action.busy()) return;
    this.mode.set(mode);
    this.passwordVisible.set(false);
    this.action.error.set('');
    this.credentials().reset({ ...this.model(), password: '', recoveryCode: '' });
  }

  async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    if (this.action.busy()) return;
    await submit(this.credentials, async () => {
      await this.action.run(async () => {
        const values = this.model();
        const mode = this.mode();
        const body =
          mode === 'recover'
            ? {
                username: values.username,
                recovery_code: values.recoveryCode,
                new_password: values.password,
              }
            : {
                username: values.username,
                password: values.password,
                ...(mode === 'register' && values.invite ? { invite_token: values.invite } : {}),
              };
        const result = await this.api.request<AccountResponse>(`/auth/${mode}`, {
          method: 'POST',
          body,
        });
        this.session.accept(result);
        this.model.set({ username: '', password: '', invite: '', recoveryCode: '' });
        await this.enterWorkspace();
      });
    });
    this.credentials().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  fieldError(field: 'username' | 'password' | 'invite' | 'recoveryCode'): string {
    const state = this.credentials[field]();
    return state.touched() ? (state.errors()[0]?.message ?? '') : '';
  }

  private async enterWorkspace(): Promise<void> {
    const authorize = this.route.snapshot.queryParamMap.get('authorize');
    await this.router.navigate(['/app'], {
      queryParams: authorize ? { authorize } : {},
      replaceUrl: true,
    });
  }
}
