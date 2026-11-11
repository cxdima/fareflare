import {
  ChangeDetectionStrategy,
  Component,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { allowsMotion } from '../core/motion';
import { SiteContentService } from '../core/site-content.service';
import { HeroComponent } from './hero.component';
import { HowComponent } from './how.component';
import { RuleDemoComponent } from './rule-demo.component';
import { ScrollSequenceComponent } from './scroll-sequence.component';

/** The website's front page: one link goes in, one alert comes out. */
@Component({
  selector: 'ff-landing',
  imports: [HeroComponent, HowComponent, RuleDemoComponent, ScrollSequenceComponent],
  templateUrl: './landing.component.html',
  styleUrl: './landing.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LandingComponent {
  private readonly site = inject(SiteContentService);
  readonly guides = computed(
    () => this.site.content()?.pages.filter((page) => page.kind === 'guide') ?? [],
  );
  /** Scroll-played pictures stay still until the browser confirms motion is welcome. */
  readonly motion = signal(false);
  readonly github = 'https://github.com/cxdima/fareflare';
  readonly apiExample =
    'curl /v1/monitors \\\n  -H "Authorization: Bearer YOUR_KEY" \\\n  -H "Idempotency-Key: my-first-flight" \\\n  -H "Content-Type: application/json" \\\n  -d \'{"url":"YOUR_GOOGLE_FLIGHTS_LINK"}\'';

  constructor() {
    afterNextRender(() => this.motion.set(allowsMotion()));
  }
}
