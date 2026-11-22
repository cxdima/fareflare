import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
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
import { message } from '../core/format';
import { PreferencesFacade } from '../core/preferences.facade';
import { observationFormatter, validTimeZone } from '../core/regional-formatting';
import type {
  MessagePreview,
  Preferences,
  PreviewKind,
  TelegramPreset,
  TelegramStyle,
  TelegramSwitch,
  TemplateCatalog,
  TemplateKey,
  TemplatePlaceholder,
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
> & {
  // The saved quiet_hours value, split into the controls that edit it.
  quiet_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
};
type TemplateModel = Record<TemplateKey, string>;
type PlaceholderGroup = { name: string; items: TemplatePlaceholder[] };

const defaultQuietHours = ['22:00', '07:00'] as const;
const clockTime = /^([01]\d|2[0-3]):[0-5]\d$/;
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
/** Long enough that typing sends one preview request, short enough to feel immediate. */
const previewDelay = 250;
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
  /** Every detail a built-in style can leave out. Each style offers the ones it shows. */
  readonly switches: { key: TelegramSwitch; id: string; label: string }[] = [
    { key: 'telegram_show_flight_numbers', id: 'show-flight-numbers', label: 'Flight numbers' },
    { key: 'telegram_show_times', id: 'show-times', label: 'Departure and arrival times' },
    {
      key: 'telegram_show_observed_time',
      id: 'show-observed-time',
      label: 'Time the price was checked',
    },
    { key: 'telegram_show_fare', id: 'show-fare', label: 'Fare name' },
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
    telegram_style: 'compact',
    telegram_show_flight_numbers: true,
    telegram_show_times: true,
    telegram_show_observed_time: true,
    telegram_show_fare: true,
    telegram_show_buttons: true,
    telegram_silent: false,
    quiet_enabled: false,
    quiet_start: defaultQuietHours[0],
    quiet_end: defaultQuietHours[1],
  });
  readonly custom = computed(() => this.telegramModel().telegram_style === 'custom');
  readonly telegram = form(this.telegramModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    validate(path.quiet_end, ({ value, valueOf }) => {
      if (!valueOf(path.quiet_enabled)) return null;
      const start = valueOf(path.quiet_start);
      return clockTime.test(start) && clockTime.test(value()) && start !== value()
        ? null
        : { kind: 'quiet-hours', message: 'Choose two different times.' };
    });
  });
  readonly templateModel = signal<TemplateModel>(emptyTemplates());
  readonly templates = form(this.templateModel, (path) => {
    disabled(path, { when: () => this.store.saving() });
    for (const key of templateKeys) maxLength(path[key], templateLimit);
  });
  readonly catalog = signal<TemplateCatalog | null>(null);
  readonly activeStyle = computed(() =>
    this.catalog()?.styles.find((style) => style.value === this.telegramModel().telegram_style),
  );
  /** Built-in styles: the ones with wording of their own to copy. */
  readonly presets = computed(
    () => this.catalog()?.styles.filter((style) => style.value !== 'custom') ?? [],
  );
  /** A custom message states its own content, so it offers none of these. */
  readonly shownSwitches = computed(() => {
    const used = new Set(this.activeStyle()?.switches ?? []);
    return this.switches.filter((item) => used.has(item.key));
  });
  readonly activeTemplate = signal<TemplateKey>('new_low');
  readonly previewKind = signal<PreviewKind>('new_low');
  /** The built-in style a first custom draft starts from. */
  private lastPreset: TelegramPreset = 'compact';
  readonly activeLength = computed(() => this.templateModel()[this.activeTemplate()].length);
  /** Details the message being edited can show, under the headings the service gives them. */
  readonly placeholderGroups = computed<PlaceholderGroup[]>(() => {
    const groups = new Map<string, TemplatePlaceholder[]>();
    for (const item of this.catalog()?.placeholders[this.activeTemplate()] ?? [])
      groups.set(item.group, [...(groups.get(item.group) ?? []), item]);
    return [...groups].map(([name, items]) => ({ name, items }));
  });
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
  readonly preview = signal<MessagePreview | null>(null);
  readonly previewBusy = signal(false);
  readonly previewError = signal('');
  private previewRequest: AbortController | null = null;
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
  /** Message settings as the API expects them; templates travel only with the custom style. */
  private readonly telegramChanges = computed<Partial<Preferences>>(() => {
    const { quiet_enabled, quiet_start, quiet_end, ...shown } = this.telegramModel();
    const changes: Partial<Preferences> = {
      ...shown,
      quiet_hours: quiet_enabled ? `${quiet_start}-${quiet_end}` : null,
    };
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
  });
  /** What the preview shows: the draft, without a quiet window that is still being typed. */
  private readonly previewRequestBody = computed<Partial<Preferences>>(() => {
    const { quiet_hours, ...changes } = this.telegramChanges();
    return this.telegram.quiet_end().valid() ? { ...changes, quiet_hours } : changes;
  });
  /** Everything a preview depends on. A new value means the shown one is out of date. */
  private readonly previewVersion = computed(() => {
    const saved = this.store.value();
    return JSON.stringify([
      this.previewRequestBody(),
      this.previewKind(),
      saved.time_zone,
      saved.locale,
      saved.hour_cycle,
    ]);
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.previewRequest?.abort());
    // The preview follows the draft: it is asked for again a moment after the last change.
    effect((onCleanup) => {
      if (this.section() !== 'notifications' || !this.store.loaded() || !this.catalog()) return;
      const version = this.previewVersion();
      const timer = setTimeout(() => void this.refreshPreview(version), previewDelay);
      onCleanup(() => clearTimeout(timer));
    });
  }

  ngOnInit(): void {
    void this.load();
    void this.loadCatalog();
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
        this.displaySaved.set(true);
      }),
    );
    this.display().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  async saveTelegram(event: Event): Promise<void> {
    event.preventDefault();
    this.telegramSaved.set(false);
    await submit(this.telegram, async () =>
      this.telegramAction.run(async () => {
        this.applyTelegram(await this.store.save(this.telegramChanges()));
        this.telegramSaved.set(true);
      }),
    );
    this.telegram().errorSummary()[0]?.fieldTree().focusBoundControl();
  }

  /** Choosing Custom starts from the wording of the style that was selected before it. */
  chooseStyle(style: TelegramStyle): void {
    if (style === this.telegramModel().telegram_style) return;
    this.telegramModel.update((value) => ({ ...value, telegram_style: style }));
    this.telegramChanged();
    if (style !== 'custom') {
      this.lastPreset = style;
      return;
    }
    const catalog = this.catalog();
    if (catalog && templateKeys.every((key) => !this.templateModel()[key]))
      this.templateModel.set({ ...catalog.presets[this.lastPreset] });
  }

  startFrom(preset: string): void {
    const templates = this.catalog()?.presets[preset as TelegramPreset];
    if (!templates) return;
    this.templateModel.set({ ...templates });
    this.telegramChanged();
  }

  /** Editing a message shows that message; the two list templates show the list. */
  editTemplate(key: string): void {
    this.activeTemplate.set(key as TemplateKey);
    this.previewKind.set(key.startsWith('flight_') ? 'flight_list' : (key as PreviewKind));
  }

  choosePreview(kind: string): void {
    this.previewKind.set(kind as PreviewKind);
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

  telegramChanged(): void {
    this.telegramSaved.set(false);
  }

  /** Ask for the preview of one version of the draft; only the newest answer is shown. */
  private async refreshPreview(version: string): Promise<void> {
    this.previewRequest?.abort();
    const request = (this.previewRequest = new AbortController());
    this.previewBusy.set(true);
    try {
      const value = await this.api.request<MessagePreview>(
        `/v1/preferences/telegram-preview?message=${untracked(this.previewKind)}`,
        { method: 'POST', body: untracked(this.previewRequestBody), signal: request.signal },
      );
      if (version !== untracked(this.previewVersion)) return;
      this.preview.set(value);
      this.previewError.set('');
    } catch (cause) {
      // A request replaced by a newer one has nothing to report.
      if (!request.signal.aborted) this.previewError.set(message(cause));
    } finally {
      if (this.previewRequest === request) {
        this.previewRequest = null;
        this.previewBusy.set(false);
      }
    }
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

  /** Styles, their wording and the details a message can show. Needed before anything is edited. */
  async loadCatalog(): Promise<void> {
    if (this.catalog()) return;
    const value = await this.catalogAction.run(() =>
      this.api.request<TemplateCatalog>('/v1/preferences/telegram-templates'),
    );
    if (value) this.catalog.set(value);
  }

  private applyTelegram(value: Preferences): void {
    const [start, end] = value.quiet_hours?.split('-') ?? [];
    this.telegramModel.set({
      telegram_style: value.telegram_style,
      telegram_show_flight_numbers: value.telegram_show_flight_numbers,
      telegram_show_times: value.telegram_show_times,
      telegram_show_observed_time: value.telegram_show_observed_time,
      telegram_show_fare: value.telegram_show_fare,
      telegram_show_buttons: value.telegram_show_buttons,
      telegram_silent: value.telegram_silent,
      quiet_enabled: value.quiet_hours !== null,
      // Keep the last window in the controls so switching it back on restores it.
      quiet_start: start ?? this.telegramModel().quiet_start,
      quiet_end: end ?? this.telegramModel().quiet_end,
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
