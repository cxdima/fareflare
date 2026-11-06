import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormField, form, maxLength, required, submit } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { RegionalFormat } from '../core/regional-format';
import type { ApiKey, Page } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { SecretComponent } from './shared/secret.component';

@Component({
  selector: 'ff-developer',
  standalone: true,
  imports: [FormField, DialogComponent, SecretComponent],
  templateUrl: './developer.component.html',
  styleUrl: './developer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeveloperComponent implements OnInit {
  readonly workspace = inject(WorkspaceFacade);
  private readonly api = inject(ApiService);
  readonly action = new ActionState();
  readonly keys = signal<ApiKey[]>([]);
  readonly secret = signal('');
  readonly revoking = signal<ApiKey | null>(null);
  readonly connection = signal<'mcp' | 'api'>('mcp');
  readonly copied = signal<'url' | 'request' | ''>('');
  readonly copyError = signal('');
  readonly model = signal({ name: '' });
  readonly keyForm = form(this.model, (path) => {
    required(path.name);
    maxLength(path.name, 80);
  });
  readonly regional = inject(RegionalFormat);
  readonly timestamp = this.regional.timestamp;
  readonly mcp = computed(
    () => this.workspace.session.config()?.mcp_url ?? `${location.origin}/mcp`,
  );
  readonly curl = `curl '${location.origin}/v1/monitors' \\\n  -H 'Authorization: Bearer YOUR_API_KEY'`;
  ngOnInit(): void {
    void this.action.run(() => this.load());
  }
  selectConnection(method: 'mcp' | 'api'): void {
    this.connection.set(method);
    this.copied.set('');
    this.copyError.set('');
  }
  async copy(value: string, kind: 'url' | 'request'): Promise<void> {
    this.copied.set('');
    this.copyError.set('');
    try {
      await navigator.clipboard.writeText(value);
      this.copied.set(kind);
    } catch {
      this.copyError.set('Copy is unavailable. Select the text and copy it manually.');
    }
  }
  status(key: ApiKey): string {
    return key.revoked ? 'Revoked' : key.expires_at * 1000 < Date.now() ? 'Expired' : 'Active';
  }
  private async load(): Promise<void> {
    this.keys.set((await this.api.request<Page<ApiKey>>('/v1/api-keys')).items);
  }
  async create(event: Event): Promise<void> {
    event.preventDefault();
    if (this.secret()) return;
    await submit(this.keyForm, async () => {
      await this.action.run(async () => {
        const result = await this.api.request<{ api_key: string }>('/v1/api-keys', {
          method: 'POST',
          body: this.model(),
        });
        this.secret.set(result.api_key);
        this.model.set({ name: '' });
        await this.load();
      });
    });
  }
  async revoke(key: ApiKey): Promise<void> {
    await this.action.run(async () => {
      await this.api.request(`/v1/api-keys/${key.id}`, { method: 'DELETE' });
      this.revoking.set(null);
      await this.load();
    });
  }
}
