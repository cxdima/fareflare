import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { flightLinkNote, keepPendingLink } from '../core/flight-link';
import { SiteContentService } from '../core/site-content.service';
import { RuleDemoComponent } from './rule-demo.component';

/** The website's front page: one link goes in, one alert comes out. */
@Component({
  selector: 'ff-landing',
  imports: [RuleDemoComponent],
  templateUrl: './landing.component.html',
  styleUrl: './landing.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingComponent {
  private readonly site = inject(SiteContentService);
  readonly guides = computed(
    () => this.site.content()?.pages.filter((page) => page.kind === 'guide') ?? [],
  );
  /** The link field in the hero: the product's one move, offered before an account exists. */
  readonly link = signal('');
  readonly linkNote = computed(() => flightLinkNote(this.link()));
  readonly github = 'https://github.com/cxdima/fareflare';
  readonly apiExample =
    'curl /v1/monitors \\\n  -H "Authorization: Bearer YOUR_KEY" \\\n  -H "Idempotency-Key: my-first-flight" \\\n  -H "Content-Type: application/json" \\\n  -d \'{"url":"YOUR_GOOGLE_FLIGHTS_LINK"}\'';

  /** A recognized link travels to sign-up and is waiting in the add-flight dialog afterwards. */
  start(event: Event, field: HTMLInputElement): void {
    event.preventDefault();
    const note = this.linkNote();
    if (note && !note.ok) {
      field.focus();
      return;
    }
    if (note) keepPendingLink(this.link());
    location.assign('/register');
  }
}
