import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import type { AdminOverview, AdminSwitches } from '../../core/types';
import { ActionState } from '../shared/action-state';

type Switch = keyof AdminSwitches;

/** Service-wide switches for an incident, and the settings the service runs with. */
@Component({
  selector: 'ff-admin-controls',
  standalone: true,
  templateUrl: './admin-controls.component.html',
  styleUrl: './admin-controls.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AdminControlsComponent implements OnInit {
  private readonly api = inject(ApiService);
  readonly switches = signal<AdminSwitches | null>(null);
  readonly config = signal<AdminOverview['config'] | null>(null);
  readonly loading = new ActionState();
  readonly saving = new ActionState();
  readonly note = signal('');

  ngOnInit(): void {
    void this.loading.run(async () => {
      const overview = await this.api.request<AdminOverview>('/v1/admin/overview');
      this.switches.set(overview.switches);
      this.config.set(overview.config);
    });
  }

  async flip(name: Switch, event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const value = input.checked;
    this.note.set('');
    const saved = await this.saving.run(async () => {
      this.switches.set(
        await this.api.request<AdminSwitches>('/v1/admin/switches', {
          method: 'PUT',
          body: { [name]: value },
        }),
      );
      return true;
    });
    if (!saved) {
      // Show the switch as it really is, not as it was clicked.
      input.checked = !value;
      return;
    }
    const messages: Record<Switch, [string, string]> = {
      registration_paused: [
        'New sign-ups are paused. Existing accounts are unaffected.',
        'Sign-ups are open again.',
      ],
      collection_paused: [
        'Price checks are paused for every flight. Due flights wait until checks resume.',
        'Price checks resumed. Flights that came due are checked first.',
      ],
    };
    this.note.set(messages[name][value ? 0 : 1]);
  }

  minutes(seconds: number): string {
    return seconds % 3600 ? `${Math.round(seconds / 60)} minutes` : `${seconds / 3600} hours`;
  }
}
