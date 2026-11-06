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
  telegram_style: 'detailed' | 'compact';
  telegram_show_flight_numbers: boolean;
  telegram_show_observed_time: boolean;
  telegram_show_fare: boolean;
  telegram_silent: boolean;
};
