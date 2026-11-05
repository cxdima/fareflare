import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly router = inject(Router);
  constructor() {
    const query = new URLSearchParams(location.search);
    const view = location.hash.slice(1).split('?')[0];
    const isLegacyView = ['monitors', 'alerts', 'webhooks', 'developer', 'settings'].includes(view);
    if (
      location.pathname === '/' &&
      (query.has('invite') || query.has('authorize') || isLegacyView)
    ) {
      void this.router.navigate(['/app'], {
        queryParams: Object.fromEntries(query),
        fragment: isLegacyView ? view : undefined,
        replaceUrl: true,
      });
    }
  }
}
