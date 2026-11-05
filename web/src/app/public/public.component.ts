import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { SiteContentService } from '../core/site-content.service';

@Component({
  selector: 'ff-public',
  templateUrl: './public.component.html',
  styleUrl: './public.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PublicComponent implements OnInit {
  readonly site = inject(SiteContentService);
  readonly path = location.pathname.replace(/\/$/, '') || '/';
  readonly page = computed(() =>
    this.site.content()?.pages.find((page) => page.path === this.path),
  );
  readonly guides = computed(
    () => this.site.content()?.pages.filter((page) => page.kind === 'guide') ?? [],
  );
  readonly error = signal(false);
  readonly alertMode = signal<'new_low' | 'below_price'>('new_low');
  readonly github = 'https://github.com/cxdima/fareflare';
  readonly apiExample =
    'curl /v1/monitors \\\n  -H "Authorization: Bearer YOUR_KEY" \\\n  -H "Idempotency-Key: my-first-flight" \\\n  -H "Content-Type: application/json" \\\n  -d \'{"url":"YOUR_GOOGLE_FLIGHTS_LINK"}\'';
  async ngOnInit(): Promise<void> {
    try {
      await this.site.load();
    } catch {
      this.error.set(true);
    }
  }
}
