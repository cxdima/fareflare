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
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { SessionFacade } from '../core/session.facade';
import { WorkspaceFacade } from './workspace.facade';
import { ActionState } from './shared/action-state';
import { MonitorsComponent } from './monitors.component';
import { AlertsComponent } from './alerts.component';
import { WebhooksComponent } from './webhooks.component';
import { DeveloperComponent } from './developer.component';
import { SettingsComponent } from './settings.component';
import { ConsentComponent } from './consent.component';
import { PreferencesFacade } from '../core/preferences.facade';
import { RegionalFormat } from '../core/regional-format';
import { TelegramFacade } from '../core/telegram.facade';

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
    MonitorsComponent,
    AlertsComponent,
    WebhooksComponent,
    DeveloperComponent,
    SettingsComponent,
    ConsentComponent,
  ],
  providers: [WorkspaceFacade, PreferencesFacade, RegionalFormat, TelegramFacade],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent implements OnInit, OnDestroy {
  readonly session = inject(SessionFacade);
  readonly workspace = inject(WorkspaceFacade);
  readonly preferences = inject(PreferencesFacade);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly title = inject(Title);
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
  private firstPrice: ReturnType<typeof setTimeout> | undefined;
  private destroyed = false;
  private readonly hashChanged = () => {
    // A settings section changes the address too; only a new page starts over.
    if (currentView() !== this.view()) this.show(currentView());
  };

  constructor() {
    effect(() => this.awaitFirstPrice());
    effect(() => this.title.setTitle(`${this.pageName()} · Fareflare`));
    effect(() => {
      if (this.session.ready() && !this.session.account() && !this.session.error()) {
        const params = this.route.snapshot.queryParams;
        // The page that was asked for is kept, so signing in arrives there.
        const asked = this.session.left() ? '' : location.hash.slice(1);
        void this.router.navigate([params['invite'] ? '/register' : '/login'], {
          queryParams: params,
          fragment: asked || undefined,
          replaceUrl: true,
        });
      }
    });
  }
  /** A flight added moments ago gets its first price shown without anyone pressing Refresh. */
  private awaitFirstPrice(): void {
    clearTimeout(this.firstPrice);
    const recent = Date.now() / 1000 - 10 * 60;
    const waiting = this.workspace
      .monitors()
      .some((item) => item.status === 'pending' && !item.latest && (item.created_at ?? 0) > recent);
    if (!waiting) return;
    this.firstPrice = setTimeout(() => {
      if (document.visibilityState === 'visible' && !this.workspace.refreshing())
        void this.workspace.refresh();
      else this.awaitFirstPrice();
    }, 12000);
  }
  async ngOnInit(): Promise<void> {
    window.addEventListener('hashchange', this.hashChanged);
    if (!this.session.ready()) await this.session.bootstrap();
    if (this.destroyed || !this.session.account()) return;
    await Promise.allSettled([this.workspace.refresh(), this.preferences.load()]);
    if (this.destroyed) return;
    this.timer = setInterval(() => {
      if (document.visibilityState === 'visible') void this.workspace.refresh();
    }, 60000);
  }
  ngOnDestroy(): void {
    this.destroyed = true;
    clearInterval(this.timer);
    clearTimeout(this.firstPrice);
    window.removeEventListener('hashchange', this.hashChanged);
  }
  select(event: Event, view: string): void {
    event.preventDefault();
    history.replaceState(null, '', location.pathname + location.search + '#' + view);
    this.show(view);
  }
  /**
   * Open a page at its top. Focus moves to the page for keyboard and screen-reader
   * users, but must not scroll: focusing a tall page left each one at a different
   * offset, with the header half off screen.
   */
  private show(view: string): void {
    this.view.set(view);
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
    requestAnimationFrame(() => this.main()?.nativeElement.focus({ preventScroll: true }));
  }
  /** The skip link does scroll: on a phone the page starts below the navigation. */
  focusMain(): void {
    requestAnimationFrame(() => this.main()?.nativeElement.focus());
  }
  async logout(): Promise<void> {
    await this.logoutAction.run(async () => {
      await this.api.request('/auth/logout', { method: 'POST' });
      this.session.leave();
      await this.router.navigate(['/login']);
    });
  }
}
