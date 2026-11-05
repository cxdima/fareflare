import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { SecretComponent } from './shared/secret.component';
import { MonitorsComponent } from './monitors.component';
import { AlertsComponent } from './alerts.component';
import { WebhooksComponent } from './webhooks.component';
import { DeveloperComponent } from './developer.component';
import { SettingsComponent } from './settings.component';
import { ConsentComponent } from './consent.component';

const navigation = [
  { id: 'monitors', label: 'Flight monitors', shortLabel: 'Flights', icon: 'bi-airplane' },
  { id: 'alerts', label: 'Alert activity', shortLabel: 'Alerts', icon: 'bi-bell' },
  { id: 'webhooks', label: 'Webhooks', shortLabel: 'Webhooks', icon: 'bi-link-45deg' },
  { id: 'developer', label: 'API & MCP', shortLabel: 'API & MCP', icon: 'bi-terminal' },
  { id: 'settings', label: 'Account settings', shortLabel: 'Account', icon: 'bi-person' },
];
function currentView(): string {
  const fragment = location.hash.slice(1).split('?')[0];
  return navigation.some((item) => item.id === fragment) ? fragment : 'monitors';
}

@Component({
  selector: 'ff-dashboard',
  standalone: true,
  imports: [
    SecretComponent,
    MonitorsComponent,
    AlertsComponent,
    WebhooksComponent,
    DeveloperComponent,
    SettingsComponent,
    ConsentComponent,
  ],
  providers: [WorkspaceFacade],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit, OnDestroy {
  readonly session = inject(SessionFacade);
  readonly workspace = inject(WorkspaceFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  readonly navigation = navigation;
  readonly view = signal(currentView());
  readonly logoutAction = new ActionState();
  readonly authorization = this.route.snapshot.queryParamMap.get('authorize');
  readonly pageName = computed(() =>
    this.authorization
      ? 'Connect application'
      : (navigation.find((item) => item.id === this.view())?.label ?? 'Flight monitors'),
  );
  readonly main = viewChild<ElementRef<HTMLElement>>('main');
  private timer: ReturnType<typeof setInterval> | undefined;
  private readonly hashChanged = () => {
    this.view.set(currentView());
    this.focusMain();
  };

  constructor() {
    effect(() => {
      if (this.session.ready() && !this.session.account() && !this.session.error()) {
        void this.router.navigate(['/login'], {
          queryParams: this.route.snapshot.queryParams,
          replaceUrl: true,
        });
      }
    });
  }
  async ngOnInit(): Promise<void> {
    if (!this.session.ready()) await this.session.bootstrap();
    if (!this.session.account()) return;
    await this.workspace.refresh();
    this.timer = setInterval(() => {
      if (document.visibilityState === 'visible') void this.workspace.refresh();
    }, 60000);
    window.addEventListener('hashchange', this.hashChanged);
  }
  ngOnDestroy(): void {
    clearInterval(this.timer);
    window.removeEventListener('hashchange', this.hashChanged);
  }
  select(event: Event, view: string): void {
    event.preventDefault();
    history.replaceState(null, '', location.pathname + location.search + '#' + view);
    this.view.set(view);
    this.focusMain();
  }
  focusMain(): void {
    requestAnimationFrame(() => this.main()?.nativeElement.focus());
  }
  async logout(): Promise<void> {
    await this.logoutAction.run(async () => {
      await this.api.request('/auth/logout', { method: 'POST' });
      this.session.clear();
      await this.router.navigate(['/login']);
    });
  }
}
