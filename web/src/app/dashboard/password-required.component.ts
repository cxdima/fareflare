import { ChangeDetectionStrategy, Component, inject, output, signal } from '@angular/core';
import { FormField, form, maxLength, minLength, required, submit } from '@angular/forms/signals';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import type { AccountResponse } from '../core/types';
import { ActionState } from './shared/action-state';

/**
 * Shown instead of the workspace after a sign-in with a temporary password, from
 * the command line or an admin. The server refuses everything else until it is done.
 */
@Component({
  selector: 'ff-password-required',
  standalone: true,
  imports: [FormField],
  templateUrl: './password-required.component.html',
  styleUrl: './password-required.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordRequiredComponent {
  readonly session = inject(SessionFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  /** Where to go next: an admin sets up a second factor before the panel opens. */
  readonly changed = output<string>();
  readonly action = new ActionState();
  readonly leaving = new ActionState();
  readonly model = signal({ current: '', next: '' });
  readonly passwordForm = form(this.model, (path) => {
    required(path.current, { message: 'Enter the temporary password you signed in with.' });
    required(path.next, { message: 'Enter a new password.' });
    minLength(path.next, 8, { message: 'Use at least 8 characters.' });
    maxLength(path.next, 128, { message: 'Use no more than 128 characters.' });
  });

  error(field: { touched: () => boolean; errors: () => { message?: string }[] }): string {
    return field.touched() ? (field.errors()[0]?.message ?? '') : '';
  }

  async save(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.passwordForm, async () => {
      await this.action.run(async () => {
        const { current, next } = this.model();
        await this.api.request('/auth/password', {
          method: 'POST',
          body: { current_password: current, new_password: next },
        });
        this.session.accept(await this.api.request<AccountResponse>('/v1/account'));
        const admin = this.session.account()?.admin;
        this.changed.emit(admin ? 'settings?section=security' : 'monitors');
      });
    });
    this.passwordForm().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  async signOut(): Promise<void> {
    await this.leaving.run(async () => {
      await this.api.request('/auth/logout', { method: 'POST' });
      this.session.leave();
      await this.router.navigate(['/login']);
    });
  }
}
