import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router, ActivatedRoute } from '@angular/router';
import {
  FormField,
  applyWhen,
  form,
  maxLength,
  minLength,
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
  readonly model = signal({ username: '', password: '', invite: '', recoveryCode: '' });
  readonly credentials = form(this.model, (path) => {
    required(path.username);
    minLength(path.username, 3);
    maxLength(path.username, 80);
    required(path.password);
    maxLength(path.password, 128);
    applyWhen(
      path.password,
      () => this.mode() !== 'login',
      (p) => minLength(p, 15),
    );
    required(path.invite, {
      when: () =>
        this.mode() === 'register' && this.session.config()?.registration_mode === 'invite',
    });
    required(path.recoveryCode, { when: () => this.mode() === 'recover' });
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
    this.mode.set(mode);
    this.action.error.set('');
    this.model.update((value) => ({ ...value, password: '', recoveryCode: '' }));
  }

  async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
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
  }

  private async enterWorkspace(): Promise<void> {
    const authorize = this.route.snapshot.queryParamMap.get('authorize');
    await this.router.navigate(['/app'], {
      queryParams: authorize ? { authorize } : {},
      replaceUrl: true,
    });
  }
}
