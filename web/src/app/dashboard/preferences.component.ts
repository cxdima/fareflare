import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import {
  FormField,
  disabled,
  form,
  maxLength,
  required,
  submit,
  validate,
} from '@angular/forms/signals';
import { ApiService } from '../core/api.service';
import { PreferencesFacade } from '../core/preferences.facade';
import { observationFormatter, validTimeZone } from '../core/regional-formatting';
import type {
  Preferences,
  PreviewKind,
  TelegramPreset,
  TemplateCatalog,
  TemplateKey,
} from '../core/types';
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
  | 'telegram_show_times'
  | 'telegram_show_observed_time'
  | 'telegram_show_fare'
  | 'telegram_show_buttons'
  | 'telegram_silent'
>;
type TemplateModel = Record<TemplateKey, string>;
type Preview = {
  text: string;
  silent: boolean;
  time_zone: string;
  buttons?: { text: string; url: string }[];
};

const templateKeys: TemplateKey[] = [
  'tracking_started',
  'new_low',
  'below_price',
  'rebound',
  'flight_group',
  'flight_row',
];
/** Mirrors the server limit so the editor stops at the same length. */
const templateLimit = 800;
const emptyTemplates = (): TemplateModel => ({
  tracking_started: '',
  new_low: '',
  below_price: '',
  rebound: '',
  flight_group: '',
  flight_row: '',
});

@Component({
  selector: 'ff-preferences',
  imports: [FormField],
  templateUrl: './preferences.component.html',
  styleUrl: './preferences.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PreferencesComponent implements OnInit {
  readonly section = input<'display' | 'notifications' | 'connections' | 'security'>('display');
  readonly store = inject(PreferencesFacade);
  private readonly api = inject(ApiService);
  readonly loading = new ActionState();
  readonly displayAction = new ActionState();
  readonly telegramAction = new ActionState();
  readonly muteAction = new ActionState();
  readonly previewAction = new ActionState();
  readonly catalogAction = new ActionState();
  readonly diagnosticsAction = new ActionState();
  readonly displaySaved = signal(false);
  readonly telegramSaved = signal(false);
  readonly muteSaved = signal(false);
  readonly diagnosticsSaved = signal(false);
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
  readonly previewKinds: { value: PreviewKind; label: string }[] = [
    { value: 'new_low', label: 'New low' },
    { value: 'tracking_started', label: 'Tracking started' },
    { value: 'below_price', label: 'Target reached' },
    { value: 'rebound', label: 'Price rebound' },
    { value: 'flight_list', label: 'Flight list' },
  ];
  readonly presets: { value: TelegramPreset; label: string }[] = [
    { value: 'detailed', label: 'Detailed' },
    { value: 'compact', label: 'Compact' },
    { value: 'classic', label: 'Classic with emoji' },
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
    telegram_show_times: true,
    telegram_show_observed_time: true,
    telegram_show_fare: true,
    telegram_show_buttons: true,
    telegram_silent: false,
  });
  readonly custom = computed(() => this.telegramModel().telegram_style === 'custom');
  readonly telegram = form(this.telegramModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    // A custom template states its own content, so these choices do not apply to it.
    const fixed = { when: () => this.store.saving() || this.custom() };
    disabled(path.telegram_show_flight_numbers, fixed);
    disabled(path.telegram_show_times, fixed);
    disabled(path.telegram_show_observed_time, fixed);
    disabled(path.telegram_show_fare, fixed);
  });
  readonly templateModel = signal<TemplateModel>(emptyTemplates());
  readonly templates = form(this.templateModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    for (const key of templateKeys) maxLength(path[key], templateLimit);
  });
  readonly catalog = signal<TemplateCatalog | null>(null);
  readonly activeTemplate = signal<TemplateKey>('new_low');
  readonly previewKind = signal<PreviewKind>('new_low');
  /** The built-in style a first custom draft starts from. */
  private lastPreset: TelegramPreset = 'detailed';
  readonly activeLength = computed(() => this.templateModel()[this.activeTemplate()].length);
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
  readonly diagnosticsModel = signal({ diagnostics: false });
  readonly diagnostics = form(this.diagnosticsModel, (path) =>
    disabled(path, { when: () => this.store.saving() }),
  );
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
      this.applyTelegram(value);
      this.muteModel.set({ muted: value.muted, routes: value.muted_routes.join(', ') });
      this.diagnosticsModel.set({ diagnostics: value.diagnostics });
      if (value.telegram_style === 'custom') void this.loadCatalog();
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
      this.applyTelegram(await this.store.save(this.telegramChanges()));
      this.telegramSaved.set(true);
    });
  }

  /** Choosing Custom starts from the wording of the style that was selected before it. */
  async styleChanged(): Promise<void> {
    this.telegramChanged();
    const style = this.telegramModel().telegram_style;
    if (style !== 'custom') {
      this.lastPreset = style;
      return;
    }
    const catalog = await this.loadCatalog();
    if (catalog && templateKeys.every((key) => !this.templateModel()[key]))
      this.templateModel.set({ ...catalog.presets[this.lastPreset] });
  }

  startFrom(preset: string): void {
    const templates = this.catalog()?.presets[preset as TelegramPreset];
    if (!templates) return;
    this.templateModel.set({ ...templates });
    this.telegramChanged();
  }

  editTemplate(key: string): void {
    this.activeTemplate.set(key as TemplateKey);
    this.previewKind.set(key.startsWith('flight_') ? 'flight_list' : (key as PreviewKind));
    this.preview.set(null);
  }

  choosePreview(kind: string): void {
    this.previewKind.set(kind as PreviewKind);
    this.preview.set(null);
  }

  /** Insert a placeholder where the cursor is, then return focus to the text. */
  insert(key: TemplateKey, name: string, area: HTMLTextAreaElement): void {
    const token = `{${name}}`;
    const start = area.selectionStart ?? area.value.length;
    const end = area.selectionEnd ?? start;
    this.templateModel.update((value) => ({
      ...value,
      [key]: value[key].slice(0, start) + token + value[key].slice(end),
    }));
    this.telegramChanged();
    // After rendering: the updated text would otherwise move the cursor to the end.
    setTimeout(() => {
      area.focus();
      area.setSelectionRange(start + token.length, start + token.length);
    });
  }

  async updatePreview(): Promise<void> {
    const version = this.previewVersion();
    await this.previewAction.run(async () => {
      const value = await this.api.request<Preview>(
        `/v1/preferences/telegram-preview?message=${this.previewKind()}`,
        { method: 'POST', body: this.telegramChanges() },
      );
      if (version === this.previewVersion()) this.preview.set(value);
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

  async saveDiagnostics(event: Event): Promise<void> {
    event.preventDefault();
    this.diagnosticsSaved.set(false);
    await this.diagnosticsAction.run(async () => {
      const saved = await this.store.save(this.diagnosticsModel());
      this.diagnosticsModel.set({ diagnostics: saved.diagnostics });
      this.diagnosticsSaved.set(true);
    });
  }

  private async loadCatalog(): Promise<TemplateCatalog | null> {
    const loaded = this.catalog();
    if (loaded) return loaded;
    const value = await this.catalogAction.run(() =>
      this.api.request<TemplateCatalog>('/v1/preferences/telegram-templates'),
    );
    if (value) this.catalog.set(value);
    return value ?? null;
  }

  /** Message settings as the API expects them; templates travel only with the custom style. */
  private telegramChanges(): Partial<Preferences> {
    const changes: Partial<Preferences> = { ...this.telegramModel() };
    if (!this.custom()) return changes;
    const optional = new Set(
      this.catalog()
        ?.templates.filter((item) => item.optional)
        .map((item) => item.key) ?? ['flight_group'],
    );
    const drafts = this.templateModel();
    changes.telegram_templates = Object.fromEntries(
      templateKeys
        .filter((key) => drafts[key].trim() || optional.has(key))
        .map((key) => [key, drafts[key]]),
    );
    return changes;
  }

  private previewVersion(): string {
    const saved = this.store.value();
    return JSON.stringify([
      this.telegramChanges(),
      this.previewKind(),
      saved.time_zone,
      saved.locale,
      saved.hour_cycle,
    ]);
  }

  private applyTelegram(value: Preferences): void {
    this.telegramModel.set({
      telegram_style: value.telegram_style,
      telegram_show_flight_numbers: value.telegram_show_flight_numbers,
      telegram_show_times: value.telegram_show_times,
      telegram_show_observed_time: value.telegram_show_observed_time,
      telegram_show_fare: value.telegram_show_fare,
      telegram_show_buttons: value.telegram_show_buttons,
      telegram_silent: value.telegram_silent,
    });
    if (value.telegram_style !== 'custom') this.lastPreset = value.telegram_style;
    // Keep an unsaved draft when the account has never stored its own templates.
    if (Object.keys(value.telegram_templates).length)
      this.templateModel.set({ ...emptyTemplates(), ...value.telegram_templates });
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
}
