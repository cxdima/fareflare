import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { ActionState } from './shared/action-state';

type ConsentDetails = {
  client_name?: string;
  name?: string;
  client_id: string;
  scopes: string[];
  resource: string;
  redirect_uri?: string;
};
@Component({
  selector: 'ff-consent',
  standalone: true,
  templateUrl: './consent.component.html',
  styleUrl: './consent.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConsentComponent implements OnInit {
  readonly id = input.required<string>();
  readonly action = new ActionState();
  readonly details = signal<ConsentDetails | null>(null);
  private readonly api = inject(ApiService);
  ngOnInit(): void {
    void this.action.run(async () =>
      this.details.set(
        await this.api.request<ConsentDetails>(
          `/v1/oauth/requests/${encodeURIComponent(this.id())}`,
        ),
      ),
    );
  }
  async decide(approve: boolean): Promise<void> {
    await this.action.run(async () => {
      const result = await this.api.request<{ redirect_url: string }>(
        `/v1/oauth/requests/${encodeURIComponent(this.id())}`,
        { method: 'POST', body: { approve } },
      );
      const url = new URL(result.redirect_url);
      if (!['http:', 'https:'].includes(url.protocol))
        throw new Error('The server returned an unsupported redirect URL.');
      location.assign(url.href);
    });
  }
}
