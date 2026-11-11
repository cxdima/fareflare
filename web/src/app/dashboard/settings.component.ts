import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { TelegramFacade } from '../core/telegram.facade';
import type { Page } from '../core/types';
import { ActionState } from './shared/action-state';
import { DialogComponent } from './shared/dialog.component';
import { TelegramConnectComponent } from './shared/telegram-connect.component';
import { PreferencesComponent } from './preferences.component';
import { SecurityComponent } from './security.component';

type Grant = {
  id: string;
  client_name: string;
  created_at: number;
  expires_at: number;
  revoked: boolean;
};
const sectionIds = ['display', 'notifications', 'connections', 'security'] as const;
type Section = (typeof sectionIds)[number];

/** Reads `#settings?section=security`, the address password managers are sent to. */
function linkedSection(): Section {
  const requested = new URLSearchParams(location.hash.split('?')[1] ?? '').get('section');
  return sectionIds.find((id) => id === requested) ?? 'display';
}

@Component({
  selector: 'ff-settings',
  standalone: true,
  imports: [DialogComponent, PreferencesComponent, SecurityComponent, TelegramConnectComponent],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsComponent implements OnInit {
  readonly sections = [
    { id: 'display', label: 'Display', icon: 'bi-globe2' },
    { id: 'notifications', label: 'Notifications', icon: 'bi-bell' },
    { id: 'connections', label: 'Connections', icon: 'bi-link-45deg' },
    { id: 'security', label: 'Security', icon: 'bi-shield-check' },
  ] as const;
  readonly section = signal<Section>(linkedSection());
  readonly session = inject(SessionFacade);
  readonly telegram = inject(TelegramFacade);
  private readonly api = inject(ApiService);
  readonly grantAction = new ActionState();
  readonly grants = signal<Grant[]>([]);
  readonly revoking = signal<Grant | null>(null);
  ngOnInit(): void {
    void this.grantAction.run(() => this.loadGrants());
  }
  /** Keeps the chosen section in the address, so a reload or a shared link returns to it. */
  open(section: Section): void {
    this.section.set(section);
    history.replaceState(
      null,
      '',
      location.pathname + location.search + '#settings?section=' + section,
    );
  }
  private async loadGrants(): Promise<void> {
    this.grants.set(
      (await this.api.request<Page<Grant>>('/v1/oauth/grants')).items.filter(
        (grant) => !grant.revoked,
      ),
    );
  }
  async revoke(grant: Grant): Promise<void> {
    await this.grantAction.run(async () => {
      await this.api.request(`/v1/oauth/grants/${grant.id}`, { method: 'DELETE' });
      this.revoking.set(null);
      await this.loadGrants();
    });
  }
}
