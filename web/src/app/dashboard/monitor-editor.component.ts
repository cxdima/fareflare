import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormField, form, max, min, required, submit } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { requestKey } from '../core/format';
import type { Monitor } from '../core/types';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { routeName } from './shared/presentation';

@Component({
  selector: 'ff-monitor-editor',
  standalone: true,
  imports: [FormField, DialogComponent],
  templateUrl: './monitor-editor.component.html',
  styleUrl: './monitor-editor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MonitorEditorComponent implements OnInit {
  readonly monitor = input<Monitor | null>(null);
  readonly closed = output<void>();
  readonly workspace = inject(WorkspaceFacade);
  private readonly api = inject(ApiService);
  readonly action = new ActionState();
  readonly routeName = routeName;
  readonly model = signal({
    url: '',
    webhook: '',
    interval: '900',
    kind: 'new_low',
    threshold: 0,
    minimum: 0,
    rebounds: false,
  });
  readonly currency = computed(() => {
    if (this.monitor()) return this.monitor()!.target.currency;
    try {
      return new URL(this.model().url).searchParams.get('curr') ?? 'USD';
    } catch {
      return 'USD';
    }
  });
  readonly unit = computed(() => (this.currency() === 'JPY' ? 1 : 100));
  readonly intervals = computed(() => [
    ...new Set(
      [this.workspace.session.config()!.limits.min_interval_seconds, 1800, 3600, 7200].filter(
        (value) => value >= this.workspace.session.config()!.limits.min_interval_seconds,
      ),
    ),
  ]);
  readonly editor = form(this.model, (path) => {
    required(path.url, { when: () => !this.monitor() });
    min(path.minimum, 0);
    max(path.minimum, 100000000);
    min(path.threshold, () => (this.model().kind === 'below_price' ? 1 / this.unit() : 0));
  });
  private attempt = { body: '', key: '' };

  ngOnInit(): void {
    const monitor = this.monitor();
    this.model.set({
      url: monitor?.target.url ?? '',
      webhook: monitor?.webhook_id ?? '',
      interval: String(
        monitor?.interval_seconds ?? this.workspace.session.config()!.limits.min_interval_seconds,
      ),
      kind: monitor?.policy.kind ?? 'new_low',
      threshold: (monitor?.policy.threshold_minor ?? 0) / this.unit(),
      minimum: (monitor?.policy.min_drop_minor ?? 0) / this.unit(),
      rebounds: monitor?.policy.notify_rebounds ?? false,
    });
  }

  async save(event: Event): Promise<void> {
    event.preventDefault();
    await submit(this.editor, async () => {
      await this.action.run(async () => {
        const value = this.model();
        const policy = {
          kind: value.kind,
          min_drop_minor: Math.round(value.minimum * this.unit()),
          threshold_minor:
            value.kind === 'below_price' ? Math.round(value.threshold * this.unit()) : null,
          notify_rebounds: value.rebounds,
        };
        const monitor = this.monitor();
        if (monitor) {
          await this.api.request(`/v1/monitors/${monitor.id}/policy`, {
            method: 'PUT',
            body: policy,
          });
        } else {
          const payload = {
            url: value.url,
            interval_seconds: Number(value.interval),
            webhook_id: value.webhook || null,
            policy,
          };
          const body = JSON.stringify(payload);
          if (body !== this.attempt.body) this.attempt = { body, key: requestKey() };
          await this.api.request('/v1/monitors', {
            method: 'POST',
            body: payload,
            key: this.attempt.key,
          });
        }
        await this.workspace.refresh();
        this.closed.emit();
      });
    });
  }
}
