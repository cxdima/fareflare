import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormField, form, required, submit } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { requestKey, timestamp } from '../core/format';
import type { Webhook } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { SecretComponent } from './shared/secret.component';

@Component({
  selector: 'ff-webhooks',
  standalone: true,
  imports: [FormField, DialogComponent, SecretComponent],
  templateUrl: './webhooks.component.html',
  styleUrl: './webhooks.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhooksComponent {
  readonly workspace = inject(WorkspaceFacade);
  private readonly api = inject(ApiService);
  readonly action = new ActionState();
  readonly items = computed(() =>
    this.workspace.webhooks().filter((item) => item.status !== 'deleted'),
  );
  readonly model = signal({ url: '' });
  readonly receiver = form(this.model, (path) => required(path.url));
  readonly verificationModel = signal({ token: '' });
  readonly verification = form(this.verificationModel, (path) => required(path.token));
  readonly verifying = signal<Webhook | null>(null);
  readonly confirmation = signal<{ item: Webhook; kind: 'disable' | 'delete' } | null>(null);
  readonly secret = signal('');
  readonly createdUrl = signal('');
  readonly note = signal('');
  readonly timestamp = timestamp;
  private attempt = { url: '', key: '' };

  async create(event: Event): Promise<void> {
    event.preventDefault();
    if (this.secret()) return;
    await submit(this.receiver, async () => {
      await this.action.run(async () => {
        const url = this.model().url;
        if (this.attempt.url !== url) this.attempt = { url, key: requestKey() };
        const result = await this.api.request<Webhook & { signing_secret?: string }>(
          '/v1/webhooks',
          { method: 'POST', body: { url }, key: this.attempt.key },
        );
        if (result.signing_secret) {
          this.secret.set(result.signing_secret);
          this.createdUrl.set(url);
        }
        this.model.set({ url: '' });
        await this.workspace.refresh();
      });
    });
  }
  async challenge(item: Webhook): Promise<void> {
    this.verifying.set(item);
    this.verificationModel.set({ token: '' });
    await this.action.run(async () => {
      const result = await this.api.request<{ delivered: boolean; expires_at: number }>(
        `/v1/webhooks/${item.id}/challenge`,
        { method: 'POST' },
      );
      this.note.set(
        result.delivered
          ? `Challenge delivered. Copy data.token from your receiver before ${timestamp(result.expires_at)}.`
          : 'The receiver did not accept the challenge. Check its logs and try again.',
      );
    });
  }
  async verify(event: Event): Promise<void> {
    event.preventDefault();
    const item = this.verifying();
    if (!item) return;
    await submit(this.verification, async () => {
      await this.action.run(async () => {
        await this.api.request(`/v1/webhooks/${item.id}/verify`, {
          method: 'POST',
          body: this.verificationModel(),
        });
        this.verificationModel.set({ token: '' });
        this.verifying.set(null);
        this.note.set('Receiver verified. You can now select it when adding a flight.');
        await this.workspace.refresh();
      });
    });
  }
  async change(): Promise<void> {
    const confirmation = this.confirmation();
    if (!confirmation) return;
    await this.action.run(async () => {
      await this.api.request(
        `/v1/webhooks/${confirmation.item.id}${confirmation.kind === 'disable' ? '/disable' : ''}`,
        { method: confirmation.kind === 'disable' ? 'POST' : 'DELETE' },
      );
      this.confirmation.set(null);
      if (this.verifying()?.id === confirmation.item.id) this.verifying.set(null);
      await this.workspace.refresh();
    });
  }
}
