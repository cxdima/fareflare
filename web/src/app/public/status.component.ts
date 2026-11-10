import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
} from '@angular/core';
import { StatusService } from '../core/status.service';
import type { StatusComponentReport, StatusHour, StatusLevel } from '../core/types';

const labels: Record<StatusLevel | 'none', string> = {
  operational: 'Working',
  degraded: 'Having trouble',
  major: 'Not working',
  unknown: 'No record yet',
  none: 'No record',
};
const names: Record<string, string> = {
  website: 'Website and API',
  price_checks: 'Price checks',
  alerts: 'Alerts',
};

/** Whether the systems behind Fareflare are working, for anyone, signed in or not. */
@Component({
  selector: 'ff-status',
  templateUrl: './status.component.html',
  styleUrl: './status.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatusComponent implements OnInit, OnDestroy {
  private readonly status = inject(StatusService);
  readonly report = this.status.report;
  readonly failed = this.status.failed;
  readonly loading = this.status.loading;
  readonly checks = computed(() =>
    this.report()?.components.find((item) => item.id === 'price_checks'),
  );
  /** One sentence that answers the question the visitor came with. */
  readonly headline = computed(() => {
    const report = this.report();
    const checks = this.checks();
    if (!report) return '';
    if (report.status === 'operational') return 'Everything is working';
    if (report.status === 'unknown') return 'No price checks have been recorded yet';
    if (checks?.reason === 'stalled') return 'Price checks are not running';
    return report.status === 'major'
      ? 'Most price checks are failing'
      : 'Some price checks are failing';
  });
  private readonly clock = new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
  private readonly hourOnly = new Intl.DateTimeFormat(undefined, { hour: 'numeric' });
  private readonly moment = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
  private timer: ReturnType<typeof setInterval> | undefined;

  ngOnInit(): void {
    void this.load();
    this.timer = setInterval(() => {
      if (document.visibilityState === 'visible') void this.load();
    }, 60000);
  }
  ngOnDestroy(): void {
    clearInterval(this.timer);
  }
  load(): Promise<void> {
    return this.status.load();
  }
  label(status: StatusLevel | 'none'): string {
    return labels[status];
  }
  name(item: StatusComponentReport): string {
    return names[item.id] ?? item.id;
  }
  time(seconds: number): string {
    return this.clock.format(seconds * 1000);
  }
  hour(item: StatusHour): string {
    return this.hourOnly.format(item.start * 1000);
  }
  detail(item: StatusComponentReport): string {
    if (item.id === 'website') return 'The website and API are answering.';
    if (item.status === 'unknown') return 'Nothing has been recorded yet.';
    if (item.id === 'alerts') {
      if (item.reason === 'stalled')
        return 'Alerts are sent when a price check records a change, so they are paused too.';
      const sent = item.sent ?? 0;
      return sent
        ? `${sent} ${sent === 1 ? 'alert' : 'alerts'} sent in the last 24 hours.`
        : 'No alerts were due in the last 24 hours.';
    }
    const last = item.last_run_at ? this.moment.format(item.last_run_at * 1000) : '';
    if (item.reason === 'stalled')
      return `No price check has run since ${last}. Prices and alerts are paused until checks resume.`;
    const share = `${item.succeeded ?? 0} of ${item.checks ?? 0} checks recorded a price in the last 24 hours`;
    if (item.status === 'major') return `Almost every check is failing. ${share}.`;
    if (item.status === 'degraded')
      return `Many checks are failing and being retried, so prices may arrive late. ${share}.`;
    return `Last run at ${this.time(item.last_run_at ?? 0)}. ${share}.`;
  }
  /** The same fact a sighted visitor reads from the bar, in words. */
  hourSummary(item: StatusHour): string {
    const from = this.hour(item);
    if (!item.runs) return `${from}: no record`;
    const total = item.collected + item.failed;
    if (!total) return `${from}: no checks were due`;
    return `${from}: ${item.collected} of ${total} checks recorded a price`;
  }
}
