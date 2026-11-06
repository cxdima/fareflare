import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormField, disabled, form, required, submit, validate } from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { PreferencesFacade } from '../core/preferences.facade';
import { observationFormatter, validTimeZone } from '../core/regional-formatting';
import type { Preferences } from '../core/types';
import { ActionState } from './shared/action-state';

type DisplayModel = {
  time_zone: string;
  locale: Preferences['locale'];
  hour_cycle: Preferences['hour_cycle'];
};
type TelegramModel = Pick<
  Preferences,
  | 'telegram_style'
  | 'telegram_show_flight_numbers'
  | 'telegram_show_observed_time'
  | 'telegram_show_fare'
  | 'telegram_silent'
>;
type Preview = { text: string; silent: boolean; time_zone: string };

@Component({
  selector: 'ff-preferences',
  imports: [FormField],
  templateUrl: './preferences.component.html',
  styleUrl: './preferences.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PreferencesComponent implements OnInit {
  readonly store = inject(PreferencesFacade);
  private readonly api = inject(ApiService);
  readonly loading = new ActionState();
  readonly displayAction = new ActionState();
  readonly telegramAction = new ActionState();
  readonly muteAction = new ActionState();
  readonly previewAction = new ActionState();
  readonly displaySaved = signal(false);
  readonly telegramSaved = signal(false);
  readonly muteSaved = signal(false);
  readonly deviceZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
  readonly zones = [
    ...new Set(['UTC', this.deviceZone, ...Intl.supportedValuesOf('timeZone')]),
  ].sort();
  readonly locales = [
    { value: 'en-US', label: 'English (United States)' },
    { value: 'en-GB', label: 'English (United Kingdom)' },
    { value: 'de-DE', label: 'Deutsch (Deutschland)' },
    { value: 'fr-FR', label: 'Français (France)' },
    { value: 'es-ES', label: 'Español (España)' },
    { value: 'uk-UA', label: 'Українська (Україна)' },
  ];
  readonly displayModel = signal<DisplayModel>({
    time_zone: this.deviceZone,
    locale: 'en-US',
    hour_cycle: 'auto',
  });
  readonly display = form(this.displayModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    required(path.time_zone, { message: 'Choose a time zone.' });
    validate(path.time_zone, ({ value }) =>
      validTimeZone(value())
        ? null
        : { kind: 'timezone', message: 'Choose a named time zone, such as America/Chicago.' },
    );
  });
  readonly telegramModel = signal<TelegramModel>({
    telegram_style: 'detailed',
    telegram_show_flight_numbers: true,
    telegram_show_observed_time: true,
    telegram_show_fare: true,
    telegram_silent: false,
  });
  readonly telegram = form(this.telegramModel, (path) =>
    disabled(path, { when: () => this.store.saving() }),
  );
  readonly muteModel = signal({ muted: false, routes: '' });
  readonly mute = form(this.muteModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    validate(path.routes, ({ value }) => {
      const routes = this.routeList(value());
      return routes.length <= 100 && routes.every((route) => /^[A-Z]{3}-[A-Z]{3}$/.test(route))
        ? null
        : {
            kind: 'routes',
            message: 'Use airport pairs like DEN-DFW, separated by commas (up to 100).',
          };
    });
  });
  readonly preview = signal<Preview | null>(null);
  private readonly sampleTime = Math.floor(Date.now() / 1000);
  readonly displayExample = computed(() => {
    const value = this.displayModel();
    return validTimeZone(value.time_zone)
      ? observationFormatter(value).format(this.sampleTime * 1000)
      : '';
  });
  readonly priceExample = computed(() =>
    new Intl.NumberFormat(this.displayModel().locale, {
      style: 'currency',
      currency: 'USD',
    }).format(1234.5),
  );
  readonly savedZone = computed(() => this.store.value().time_zone ?? 'UTC');

  ngOnInit(): void {
    void this.load();
  }

  async load(): Promise<void> {
    await this.loading.run(async () => {
      const value = await this.store.load();
      this.displayModel.set({
        time_zone: value.time_zone ?? this.deviceZone,
        locale: value.locale,
        hour_cycle: value.hour_cycle,
      });
      this.telegramModel.set(this.telegramFields(value));
      this.muteModel.set({ muted: value.muted, routes: value.muted_routes.join(', ') });
    });
  }

  useDeviceZone(): void {
    this.displayModel.update((value) => ({ ...value, time_zone: this.deviceZone }));
    this.displaySaved.set(false);
  }

  async saveDisplay(event: Event): Promise<void> {
    event.preventDefault();
    this.displaySaved.set(false);
    await submit(this.display, async () =>
      this.displayAction.run(async () => {
        await this.store.save(this.displayModel());
        this.preview.set(null);
        this.displaySaved.set(true);
      }),
    );
    this.display().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  async saveTelegram(event: Event): Promise<void> {
    event.preventDefault();
    this.telegramSaved.set(false);
    await this.telegramAction.run(async () => {
      const value = await this.store.save(this.telegramModel());
      this.telegramModel.set(this.telegramFields(value));
      this.telegramSaved.set(true);
    });
  }

  async updatePreview(): Promise<void> {
    const changes = { ...this.telegramModel() };
    const version = JSON.stringify([
      changes,
      this.store.value().time_zone,
      this.store.value().locale,
      this.store.value().hour_cycle,
    ]);
    await this.previewAction.run(async () => {
      const value = await this.api.request<Preview>('/v1/preferences/telegram-preview', {
        method: 'POST',
        body: changes,
      });
      if (
        version ===
        JSON.stringify([
          this.telegramModel(),
          this.store.value().time_zone,
          this.store.value().locale,
          this.store.value().hour_cycle,
        ])
      )
        this.preview.set(value);
    });
  }

  telegramChanged(): void {
    this.telegramSaved.set(false);
    this.preview.set(null);
  }

  async saveMute(event: Event): Promise<void> {
    event.preventDefault();
    this.muteSaved.set(false);
    await submit(this.mute, async () =>
      this.muteAction.run(async () => {
        const value = this.muteModel();
        const saved = await this.store.save({
          muted: value.muted,
          muted_routes: this.routeList(value.routes),
        });
        this.muteModel.set({ muted: saved.muted, routes: saved.muted_routes.join(', ') });
        this.muteSaved.set(true);
      }),
    );
    this.mute().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  private routeList(value: string): string[] {
    return [
      ...new Set(
        value
          .split(',')
          .map((route) => route.trim().toUpperCase())
          .filter(Boolean),
      ),
    ];
  }
  private telegramFields(value: Preferences): TelegramModel {
    return {
      telegram_style: value.telegram_style,
      telegram_show_flight_numbers: value.telegram_show_flight_numbers,
      telegram_show_observed_time: value.telegram_show_observed_time,
      telegram_show_fare: value.telegram_show_fare,
      telegram_silent: value.telegram_silent,
    };
  }
}
