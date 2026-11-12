export type ProductConfig = {
  product_name: string;
  billing_enabled: boolean;
  registration_mode: 'open' | 'closed';
  /** Password resets and address confirmation need a mail provider on the server. */
  email_enabled?: boolean;
  limits: { monitors: number; min_interval_seconds: number };
  mcp_url?: string;
  capabilities?: { route_searches?: boolean };
};
export type Account = {
  id: string;
  username: string;
  created_at?: number;
  email?: string | null;
  email_verified?: boolean;
  /** Admins see the admin panel; the role is granted only from the command line. */
  admin?: boolean;
  /** Signed in with a temporary password: nothing else works until it is replaced. */
  must_change_password?: boolean;
};
export type AccountResponse = { account: Account; csrf_token: string };
/** A password sign-in that still needs a code from an authenticator app. */
export type TwoFactorChallenge = { two_factor_required: true; token: string; expires_at: number };
export type PasskeyOptions = { challenge_id: string; options: Record<string, unknown> };
export type Passkey = {
  id: string;
  credential_id: string;
  name: string;
  provider: string;
  synced: boolean;
  created_at: number;
  last_used_at: number | null;
};
export type Security = {
  email: string | null;
  email_verified: boolean;
  email_enabled: boolean;
  two_factor: { enabled: boolean; backup_codes_left: number; enabled_at: number | null };
  passkeys: Passkey[];
};
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
  created_at?: number;
  latest: Observation | null;
  /** The lowest total this monitor has recorded since it started. */
  low_minor?: number | null;
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

export type StatusLevel = 'operational' | 'degraded' | 'major' | 'unknown';
export interface StatusComponentReport {
  id: string;
  status: StatusLevel;
  reason: 'stalled' | 'failing' | null;
  last_run_at?: number | null;
  checks?: number;
  succeeded?: number;
  sent?: number;
}
export interface StatusHour {
  start: number;
  runs: number;
  collected: number;
  failed: number;
  alerts_sent: number;
  status: 'operational' | 'degraded' | 'major' | 'none';
}
export interface StatusReport {
  status: StatusLevel;
  updated_at: number;
  window_hours: number;
  components: StatusComponentReport[];
  hours: StatusHour[];
}

// The admin panel.
export type AdminGate = {
  ready: boolean;
  reason: 'password' | 'mfa' | 'reauth' | null;
  message: string | null;
  expires_at: number | null;
};
export type AdminSwitches = { registration_paused: boolean; collection_paused: boolean };
export type AdminUserRow = {
  id: string;
  email: string | null;
  status: 'active' | 'suspended' | 'deleted';
  admin: boolean;
  created_at: number | null;
  last_sign_in_at: number | null;
  email_verified: boolean;
  two_factor: boolean;
  passkeys: number;
  api_keys: number;
  flights: number;
  telegram: boolean;
  must_change_password: boolean;
  suspended_at: number | null;
};
export type AdminUsers = {
  items: AdminUserRow[];
  total: number;
  offset: number;
  limit: number;
  truncated: boolean;
};
export type AuditEntry = {
  at: number;
  action: string;
  admin_id: string;
  admin: string;
  target_id: string | null;
  target: string | null;
  detail: Record<string, string | boolean>;
};
export type AdminUser = {
  account: AdminUserRow & {
    sessions: number;
    suspended_reason: string | null;
    temporary_password_expires_at: number | null;
    alerts_muted: boolean;
  };
  flights: Monitor[];
  alerts: {
    id: string;
    monitor_id: string;
    reason: string;
    status: string;
    attempts: number;
    observed_at: number | null;
    amount_minor: number | null;
    currency: string | null;
  }[];
  api_keys: { name: string; created_at: number | null; expires_at: number; revoked: boolean }[];
  passkeys: { name: string; provider: string; created_at: number; last_used_at: number | null }[];
  applications: { client_name: string; created_at: number; revoked: boolean }[];
  webhooks: { host: string; status: string; created_at: number | null }[];
  audit: AuditEntry[];
};
export type Budget = { used: number; limit: number };
export type AdminOverview = {
  generated_at: number;
  users: {
    total: number;
    active: number;
    suspended: number;
    deleted: number;
    admins: number;
    new_day: number;
    new_week: number;
    new_month: number;
    signed_in_week: number;
    signed_in_month: number;
    email_verified: number;
    two_factor: number;
    passkeys: number;
    telegram: number;
    api_keys: number;
    truncated: boolean;
  };
  signups: { day: number; count: number }[];
  flights: {
    watched: number;
    by_status: Record<string, number>;
    targets: { collecting: number; blocked: number; idle: number };
    capacity: { used: number; limit: number | null };
  };
  collection: StatusReport;
  email: Record<'confirm' | 'reset' | 'notice', { hour: Budget; day: Budget }>;
  switches: AdminSwitches;
  config: {
    registration_mode: 'open' | 'closed';
    email_enabled: boolean;
    breach_check: boolean;
    monitor_limit: number;
    global_target_limit: number | null;
    min_interval_seconds: number;
  };
};
export type AdminFlight = {
  id: string;
  state: 'collecting' | 'blocked' | 'idle';
  target: Monitor['target'];
  latest: Observation | null;
  failures: number;
  last_error: string | null;
  next_check_at: number | null;
  interval_seconds: number | null;
  watcher_count: number;
  watchers: {
    monitor_id: string;
    account_id: string;
    email: string | null;
    status: Monitor['status'];
    interval_seconds: number;
    created_at: number | null;
  }[];
};
export type AdminFlights = {
  items: AdminFlight[];
  capacity: { used: number; limit: number | null };
  expired: number;
};
