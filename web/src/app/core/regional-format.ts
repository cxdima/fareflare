import { Injectable, computed, inject } from '@angular/core';
import { PreferencesFacade } from './preferences.facade';
import {
  clockFormatter,
  currencyFormat,
  departureFormatter,
  observationFormatter,
} from './regional-formatting';

/** Cached Intl formatters react to the account's saved display preferences. */
@Injectable()
export class RegionalFormat {
  private readonly preferences = inject(PreferencesFacade);
  private readonly observations = computed(() => observationFormatter(this.preferences.value()));
  private readonly departures = computed(() => departureFormatter(this.preferences.value().locale));
  private readonly clocks = computed(() => clockFormatter(this.preferences.value()));
  private readonly numbers = computed(
    () => new Intl.NumberFormat(this.preferences.value().locale, { maximumFractionDigits: 1 }),
  );
  private readonly currencies = computed(() => ({
    locale: this.preferences.value().locale,
    values: new Map<string, Intl.NumberFormat>(),
  }));
  readonly zone = computed(() => this.observations().resolvedOptions().timeZone);
  readonly timestamp = (seconds: number): string => this.observations().format(seconds * 1000);
  readonly tripDate = (date: string): string =>
    this.departures().format(new Date(date + 'T12:00:00Z'));
  /** A stored 24-hour airport time, such as 15:50, in the account's clock style. */
  readonly clock = (value: string): string =>
    this.clocks().format(new Date(`1970-01-01T${value}:00Z`));
  readonly number = (value: number): string => this.numbers().format(value);
  readonly money = (amount: number, currency: string): string => {
    const cache = this.currencies();
    let formatter = cache.values.get(currency);
    if (!formatter) {
      formatter = currencyFormat(cache.locale, currency);
      cache.values.set(currency, formatter);
    }
    return formatter.format(amount / (currency === 'JPY' ? 1 : 100));
  };
}
