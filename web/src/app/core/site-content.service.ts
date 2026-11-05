import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';

export interface ContentSection {
  heading: string;
  paragraphs: string[];
  bullets: string[];
  links: { label: string; href: string }[];
  code?: string;
}
export interface PublicPage {
  path: string;
  title: string;
  description: string;
  eyebrow: string;
  headline: string;
  intro: string;
  sections: ContentSection[];
  kind: 'page' | 'guide';
  published?: string;
  modified?: string;
  read_minutes?: number;
}
export interface SiteContent {
  github_url: string;
  product_name: string;
  pages: PublicPage[];
}

@Injectable({ providedIn: 'root' })
export class SiteContentService {
  private readonly api = inject(ApiService);
  readonly content = signal<SiteContent | null>(null);
  private pending: Promise<SiteContent> | null = null;
  async load(): Promise<SiteContent> {
    this.pending ??= this.api.request<SiteContent>('/site-content.json').catch((error) => {
      this.pending = null;
      throw error;
    });
    const content = await this.pending;
    this.content.set(content);
    return content;
  }
}
