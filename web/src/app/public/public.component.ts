import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { SiteContentService } from '../core/site-content.service';
import { LandingComponent } from './landing.component';
import { StatusComponent } from './status.component';

@Component({
  selector: 'ff-public',
  imports: [LandingComponent, StatusComponent],
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
  readonly github = 'https://github.com/cxdima/fareflare';
  async ngOnInit(): Promise<void> {
    try {
      await this.site.load();
    } catch {
      this.error.set(true);
    }
  }
}
