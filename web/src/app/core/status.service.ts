import { Injectable, computed, signal } from '@angular/core';
import type { StatusReport } from './types';

/** The public system status, shared by the status page and the workspace header. */
@Injectable({ providedIn: 'root' })
export class StatusService {
  readonly report = signal<StatusReport | null>(null);
  readonly failed = signal(false);
  readonly loading = signal(false);
  /** A short answer for places with room for a few words. */
  readonly summary = computed(() => {
    switch (this.report()?.status) {
      case 'operational':
        return 'All systems working';
      case 'degraded':
        return 'Price checks are having trouble';
      case 'major':
        return 'Price checks are not working';
      default:
        return 'System status';
    }
  });

  async load(): Promise<void> {
    this.loading.set(true);
    try {
      const response = await fetch('/v1/status', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('status');
      const report = (await response.json()) as StatusReport;
      if (!Array.isArray(report.components) || !Array.isArray(report.hours))
        throw new Error('status');
      this.report.set(report);
      this.failed.set(false);
    } catch {
      // A report already loaded stays; it says when it was last updated.
      this.failed.set(true);
    } finally {
      this.loading.set(false);
    }
  }
}
