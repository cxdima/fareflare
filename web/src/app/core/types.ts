export type ProductConfig = {
  product_name: string;
  billing_enabled: boolean;
  registration_mode: 'invite' | 'open' | 'closed';
  limits: { monitors: number; min_interval_seconds: number };
  mcp_url?: string;
  capabilities?: { route_searches?: boolean };
};
export type Account = { id: string; username: string; created_at?: number };
export type AccountResponse = { account: Account; csrf_token: string; recovery_code?: string };
/** Airport-local clock times for one direction, as 24-hour HH:MM. */
export type SliceTimes = {
  departs: string;
  arrives: string;
  arrival_day_offset?: number;
  duration_minutes?: number | null;
};
export type Observation = {
  amount_minor: number;
  currency: string;
  observed_at: number;
  fare_name: string | null;
  price_basis: 'total' | 'unspecified';
  source: string;
  observed_offer?: {
    target_id?: string;
    segments: Segment[];
    adults: number;
    cabin: number;
    url: string;
  } | null;
  schedule?: SliceTimes[] | null;
};
export type Leg = {
  origin: string;
  destination: string;
  airline: string | null;
  number: string | null;
  date: string;
};
export type Segment = { date: string; legs: Leg[] };
export type Monitor = {
  id: string;
  status: 'pending' | 'active' | 'paused' | 'cancelled' | 'expired' | 'degraded';
  target: {
    kind?: 'selected' | 'search';
    segments: Segment[];
    adults: number;
    currency: string;
    url: string;
  };
  interval_seconds: number;
  latest: Observation | null;
  stale: boolean;
  last_error: string | null;
  collection_failures?: number;
  collection_status: string;
  next_check_at: number | null;
  webhook_id: string | null;
  policy: {
    kind: 'new_low' | 'below_price';
    min_drop_minor: number;
    threshold_minor: number | null;
    notify_rebounds: boolean;
  };
};
export type Webhook = {
  id: string;
  url: string;
  status: 'pending' | 'active' | 'disabled' | 'deleted';
  created_at: number;
  verified_at: number | null;
};
export type Alert = {
  id: string;
  monitor_id: string;
  reason: string;
  status: 'pending' | 'sent' | 'dead_letter' | 'suppressed';
  attempts: number;
  observation: Observation;
  webhook_id: string | null;
};
export type ApiKey = {
  id: string;
  name?: string;
  created_at?: number;
  expires_at: number;
  revoked: boolean;
};
export type Page<T> = { items: T[]; next_cursor?: string | null };
export type Preferences = {
  muted: boolean;
  muted_routes: string[];
  time_zone: string | null;
  locale: 'en-US' | 'en-GB' | 'de-DE' | 'fr-FR' | 'es-ES' | 'uk-UA';
  hour_cycle: 'auto' | 'h12' | 'h23';
  telegram_style: TelegramStyle;
  telegram_templates: Partial<Record<TemplateKey, string>>;
  telegram_show_flight_numbers: boolean;
  telegram_show_times: boolean;
  telegram_show_observed_time: boolean;
  telegram_show_fare: boolean;
  telegram_show_buttons: boolean;
  telegram_silent: boolean;
  /** A daily window such as 22:00-07:00, in the account time zone; null when off. */
  quiet_hours: string | null;
  diagnostics: boolean;
};
export type TelegramStyle = 'detailed' | 'compact' | 'classic' | 'custom';
export type TelegramPreset = Exclude<TelegramStyle, 'custom'>;
export type TemplateKey =
  'tracking_started' | 'new_low' | 'below_price' | 'rebound' | 'flight_group' | 'flight_row';
export type PreviewKind = Exclude<TemplateKey, 'flight_group' | 'flight_row'> | 'flight_list';
export type TemplatePlaceholder = { name: string; description: string; example: string };
export type TemplateCatalog = {
  templates: { key: TemplateKey; label: string; optional: boolean }[];
  placeholders: Record<TemplateKey, TemplatePlaceholder[]>;
  presets: Record<TelegramPreset, Record<TemplateKey, string>>;
  limits: { characters: number; lines: number; placeholders: number };
};
