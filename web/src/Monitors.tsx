import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, money, requestKey, safeFlightUrl, timestamp, tripDate } from './api';
import type { Monitor, Observation, Page, ProductConfig, Segment, Webhook } from './types';
import { Button, Dialog, Empty, Icon, Notice, Status, useAction } from './ui';

export function routeName(monitor: Monitor) {
  const legs = monitor.target.segments[0]?.legs ?? [];
  return legs.length
    ? `${legs[0].origin} → ${legs[legs.length - 1].destination}`
    : 'Selected itinerary';
}

function flightNumbers(segments: Segment[]) {
  return segments
    .flatMap((segment) => segment.legs)
    .filter((leg) => leg.airline && leg.number)
    .map((leg) => `${leg.airline} ${leg.number}`)
    .join(' · ');
}

function History({ monitor, onClose }: { monitor: Monitor; onClose: () => void }) {
  const [items, setItems] = useState<Observation[]>([]);
  const [cursor, setCursor] = useState<string | null>();
  const action = useAction();
  async function load(next?: string) {
    await action.run(async () => {
      const page = await api<Page<Observation>>(
        `/v1/monitors/${monitor.id}/history${next ? `?cursor=${encodeURIComponent(next)}` : ''}`,
      );
      setItems((previous) => (next ? [...previous, ...page.items] : page.items));
      setCursor(page.next_cursor);
    });
  }
  useEffect(() => {
    void load();
  }, [monitor.id]);
  const ordered = [...items].sort((a, b) => a.observed_at - b.observed_at);
  const values = ordered.map((item) => item.amount_minor);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const start = ordered[0]?.observed_at ?? 0;
  const end = ordered.at(-1)?.observed_at ?? 0;
  const points = ordered
    .map(
      (item) =>
        `${30 + ((item.observed_at - start) / (end - start || 1)) * 640},${145 - ((item.amount_minor - low) / (high - low || 1)) * 115}`,
    )
    .join(' ');
  return (
    <Dialog title={`${routeName(monitor)} price history`} onClose={onClose}>
      <p className="muted">
        Observed totals for {monitor.target.adults}{' '}
        {monitor.target.adults === 1 ? 'adult' : 'adults'}. Gaps mean no observation was recorded.
      </p>
      {action.error && <Notice danger>{action.error}</Notice>}
      {items.length > 0 ? (
        <>
          <div className="history-summary">
            <div>
              <span className="eyebrow">Lowest shown</span>
              <strong>{money(low, monitor.target.currency)}</strong>
            </div>
            <div>
              <span className="eyebrow">Observations</span>
              <strong>{items.length}</strong>
            </div>
          </div>
          {items.length > 1 && (
            <svg
              className="price-chart"
              viewBox="0 0 700 180"
              role="img"
              aria-label={`Observed price history, from ${money(ordered[0].amount_minor, monitor.target.currency)} to ${money(ordered.at(-1)!.amount_minor, monitor.target.currency)}. All values are in the table below.`}
            >
              <line x1="30" y1="155" x2="670" y2="155" stroke="#d9e2e5" />
              <polyline
                points={points}
                fill="none"
                stroke="#176c50"
                strokeWidth="3"
                strokeLinejoin="round"
              />
            </svg>
          )}
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Price observations, most recent first</caption>
              <thead>
                <tr>
                  <th scope="col">Observed</th>
                  <th scope="col">Total price</th>
                  <th scope="col">Fare</th>
                  {monitor.target.kind === 'search' && <th scope="col">Matching flight</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((item, index) => (
                  <tr key={`${item.observed_at}-${index}`}>
                    <td>{timestamp(item.observed_at)}</td>
                    <td>{money(item.amount_minor, item.currency)}</td>
                    <td>{item.fare_name ?? 'Not specified'}</td>
                    {monitor.target.kind === 'search' && (
                      <td>
                        {item.observed_offer
                          ? flightNumbers(item.observed_offer.segments)
                          : 'Not recorded'}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cursor && (
            <Button busy={action.busy} onClick={() => void load(cursor)}>
              Load earlier observations
            </Button>
          )}
        </>
      ) : (
        <Empty title={action.busy ? 'Loading observations…' : 'Your first price is on its way'}>
          A price history will appear after the first successful check.
        </Empty>
      )}
    </Dialog>
  );
}

function CreateMonitor({
  config,
  webhooks,
  onCreated,
  onClose,
}: {
  config: ProductConfig;
  webhooks: Webhook[];
  onCreated: () => Promise<void>;
  onClose: () => void;
}) {
  const [url, setUrl] = useState('');
  const [webhook, setWebhook] = useState('');
  const [interval, setInterval] = useState(config.limits.min_interval_seconds);
  const [kind, setKind] = useState<'new_low' | 'below_price'>('new_low');
  const [threshold, setThreshold] = useState('');
  const attempt = useRef({ body: '', key: '' });
  const action = useAction();
  let currency = 'USD';
  try {
    currency = new URL(url).searchParams.get('curr') ?? 'USD';
  } catch {
    /* validated on submit */
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const payload = {
        url,
        interval_seconds: interval,
        webhook_id: webhook || null,
        policy: {
          kind,
          min_drop_minor: 0,
          threshold_minor:
            kind === 'below_price'
              ? Math.round(Number(threshold) * (currency === 'JPY' ? 1 : 100))
              : null,
          notify_rebounds: false,
        },
      };
      const body = JSON.stringify(payload);
      if (body !== attempt.current.body) attempt.current = { body, key: requestKey() };
      await api('/v1/monitors', { method: 'POST', body: payload, key: attempt.current.key });
      await onCreated();
      onClose();
    });
  }
  return (
    <Dialog title="Watch a flight" onClose={onClose}>
      <p className="muted">
        {config.capabilities?.route_searches
          ? 'Paste a fixed-date Google Flights route search, or choose your flights and copy the address after selecting the complete itinerary.'
          : 'Choose your flights on Google Flights, then copy the address after selecting the complete itinerary.'}
      </p>
      <div className="info-panel">
        <strong>What works today</strong>
        <p>
          Selected nonstop itineraries, one way or round trip, economy, 1–2 adults, in USD or JPY.
          Flexible date and destination searches are not supported yet.
        </p>
        {config.capabilities?.route_searches && (
          <p>
            Route searches: exact airports and date, one way, nonstop, 1 adult, economy excluding
            Basic, USD, with Google Flights set to US English. We watch the cheapest eligible offer
            observed in that search.
          </p>
        )}
      </div>
      {action.error && <Notice danger>{action.error}</Notice>}
      <form onSubmit={submit} className="form-stack">
        <label>
          Google Flights link
          <textarea
            name="flight_url"
            required
            rows={3}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://www.google.com/travel/flights?..."
            spellCheck={false}
          />
        </label>
        <div className="form-grid">
          <label>
            Check interval
            <select value={interval} onChange={(event) => setInterval(Number(event.target.value))}>
              {[
                ...new Set(
                  [config.limits.min_interval_seconds, 1800, 3600, 7200].filter(
                    (value) => value >= config.limits.min_interval_seconds,
                  ),
                ),
              ].map((value) => (
                <option key={value} value={value}>
                  Every {value / 60} minutes
                </option>
              ))}
            </select>
          </label>
          <label>
            Notify me when
            <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
              <option value="new_low">A new observed low appears</option>
              <option value="below_price">The price is below my target</option>
            </select>
          </label>
        </div>
        {kind === 'below_price' && (
          <label>
            Target total ({currency})
            <input
              type="number"
              required
              min={currency === 'JPY' ? 1 : 0.01}
              step={currency === 'JPY' ? 1 : 0.01}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </label>
        )}
        <label>
          Alert destination
          <select value={webhook} onChange={(event) => setWebhook(event.target.value)}>
            <option value="">Telegram if connected; otherwise dashboard</option>
            {webhooks
              .filter((item) => item.status === 'active')
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.url}
                </option>
              ))}
          </select>
        </label>
        <p className="field-hint">
          Connect Telegram in Account settings, or verify a receiver in Webhooks. A selected webhook
          receives this monitor’s outgoing alerts instead of Telegram. Checks may be delayed; a fare
          can change between checks.
        </p>
        <div className="actions end">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" kind="primary" busy={action.busy}>
            Start watching
            <Icon name="arrow" size={17} />
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function EditPolicy({
  monitor,
  refresh,
  onClose,
}: {
  monitor: Monitor;
  refresh: () => Promise<void>;
  onClose: () => void;
}) {
  const [kind, setKind] = useState(monitor.policy.kind);
  const unit = monitor.target.currency === 'JPY' ? 1 : 100;
  const [threshold, setThreshold] = useState(
    monitor.policy.threshold_minor === null ? '' : String(monitor.policy.threshold_minor / unit),
  );
  const [minimum, setMinimum] = useState(String(monitor.policy.min_drop_minor / unit));
  const [rebounds, setRebounds] = useState(monitor.policy.notify_rebounds);
  const action = useAction();
  async function save(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await api(`/v1/monitors/${monitor.id}/policy`, {
        method: 'PUT',
        body: {
          kind,
          min_drop_minor: Math.round(Number(minimum) * unit),
          threshold_minor: kind === 'below_price' ? Math.round(Number(threshold) * unit) : null,
          notify_rebounds: rebounds,
        },
      });
      await refresh();
      onClose();
    });
  }
  return (
    <Dialog title="Edit price alerts" onClose={onClose}>
      <p>
        Choose what should trigger an alert for {routeName(monitor)}. Amounts are totals for your
        selected party.
      </p>
      {action.error && <Notice danger>{action.error}</Notice>}
      <form onSubmit={save} className="form-stack">
        <label>
          Notify me when
          <select value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
            <option value="new_low">A new observed low appears</option>
            <option value="below_price">The price is below my target</option>
          </select>
        </label>
        {kind === 'below_price' && (
          <label>
            Target total ({monitor.target.currency})
            <input
              required
              type="number"
              min={1 / unit}
              step={1 / unit}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
            />
          </label>
        )}
        <label>
          Minimum price drop ({monitor.target.currency})
          <input
            type="number"
            required
            min="0"
            step={1 / unit}
            value={minimum}
            onChange={(event) => setMinimum(event.target.value)}
          />
        </label>
        <p className="field-hint">Use 0 to include every qualifying price drop.</p>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={rebounds}
            onChange={(event) => setRebounds(event.target.checked)}
          />
          Also alert when the price rises
        </label>
        <div className="actions end">
          <Button onClick={onClose}>Cancel</Button>
          <Button kind="primary" type="submit" busy={action.busy}>
            Save alert policy
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function MonitorCard({
  monitor,
  refresh,
  onHistory,
}: {
  monitor: Monitor;
  refresh: () => Promise<void>;
  onHistory: () => void;
}) {
  const action = useAction();
  const [confirm, setConfirm] = useState(false);
  const [editing, setEditing] = useState(false);
  const current = !['cancelled', 'expired'].includes(monitor.status);
  const search = monitor.target.kind === 'search';
  const url = safeFlightUrl(monitor.latest?.observed_offer?.url ?? monitor.target.url);
  const flights = flightNumbers(
    monitor.latest?.observed_offer?.segments ?? monitor.target.segments,
  );
  async function change(status: string) {
    await action.run(async () => {
      await api(`/v1/monitors/${monitor.id}`, { method: 'PATCH', body: { status } });
      await refresh();
      setConfirm(false);
    });
  }
  return (
    <article className="monitor-card" aria-label={`${routeName(monitor)} monitor`}>
      <div className="monitor-top">
        <div className="route">
          <span className="route-icon">
            <Icon name="plane" size={21} />
          </span>
          <div>
            <h2>{routeName(monitor)}</h2>
            <p>
              {monitor.target.segments.map((segment) => tripDate(segment.date)).join(' · ')}
              <span className="sep">/</span>
              {monitor.target.segments.length > 1 ? 'Round trip' : 'One way'}
            </p>
            {search ? <p>Cheapest matching route</p> : flights && <p>{flights}</p>}
          </div>
        </div>
        <Status value={monitor.status} />
      </div>
      <div className="monitor-middle">
        <div>
          <span className="eyebrow">Latest observed total</span>
          <div className="price">
            {monitor.latest ? (
              money(monitor.latest.amount_minor, monitor.latest.currency)
            ) : (
              <span className="price-pending">Awaiting first check</span>
            )}
          </div>
          <p className="muted">
            {monitor.target.adults} {monitor.target.adults === 1 ? 'adult' : 'adults'} · Economy
            {monitor.latest?.fare_name && monitor.latest.fare_name.toLowerCase() !== 'economy'
              ? ` · ${monitor.latest.fare_name}`
              : ''}
          </p>
        </div>
        <div className="observation-meta">
          {search && flights && <span>Latest match: {flights}</span>}
          {monitor.latest ? (
            <>
              <span>
                <Icon name="clock" size={16} />
                Observed {timestamp(monitor.latest.observed_at)}
              </span>
              {monitor.stale && <Status value="stale" />}
            </>
          ) : (
            <span>No price recorded yet</span>
          )}
          <span>
            Checks every {monitor.interval_seconds / 60} min
            {monitor.next_check_at && current && monitor.status !== 'paused'
              ? ` · Next ${timestamp(monitor.next_check_at)}`
              : ''}
          </span>
        </div>
      </div>
      {monitor.last_error && (
        <div className="collection-note">
          <Icon name="clock" size={16} />
          <span>The latest check did not finish. {monitor.last_error.replaceAll('_', ' ')}.</span>
        </div>
      )}
      <div className="monitor-footer">
        <span className="policy-description">
          {monitor.policy.kind === 'below_price'
            ? `Alert below ${money(monitor.policy.threshold_minor ?? 0, monitor.target.currency)}`
            : 'Alert on a new observed low'}{' '}
          · {monitor.webhook_id ? 'Webhook connected' : 'Account alerts'}
        </span>
        <div className="actions compact">
          <Button kind="ghost" onClick={onHistory}>
            Price history
          </Button>
          {url && (
            <a className="button ghost" href={url} target="_blank" rel="noreferrer">
              {search && !monitor.latest?.observed_offer ? 'View search' : 'View flight'}
              <Icon name="external" size={14} />
              <span className="sr-only"> (opens a new tab)</span>
            </a>
          )}
          {current && (
            <>
              <Button kind="ghost" onClick={() => setEditing(true)}>
                Edit alerts
              </Button>
              <Button
                busy={action.busy}
                onClick={() => void change(monitor.status === 'paused' ? 'active' : 'paused')}
              >
                {monitor.status === 'paused' ? 'Resume' : 'Pause'}
              </Button>
              <Button kind="ghost" onClick={() => setConfirm(true)}>
                Stop
              </Button>
            </>
          )}
        </div>
      </div>
      {current && monitor.collection_status === 'blocked' && (
        <Button
          busy={action.busy}
          onClick={() =>
            void action.run(async () => {
              await api(`/v1/monitors/${monitor.id}/retry-collection`, { method: 'POST' });
              await refresh();
            })
          }
        >
          Retry collection
        </Button>
      )}
      {action.error && <Notice danger>{action.error}</Notice>}
      {editing && (
        <EditPolicy monitor={monitor} refresh={refresh} onClose={() => setEditing(false)} />
      )}
      {confirm && (
        <Dialog title="Stop watching this flight?" onClose={() => setConfirm(false)}>
          <p>
            Checks and new alerts for {routeName(monitor)} will stop. Its existing history stays
            available.
          </p>
          <div className="actions end">
            <Button onClick={() => setConfirm(false)}>Keep watching</Button>
            <Button kind="danger" busy={action.busy} onClick={() => void change('cancelled')}>
              Stop watching
            </Button>
          </div>
        </Dialog>
      )}
    </article>
  );
}

export function Monitors({
  items,
  webhooks,
  config,
  refresh,
  loading,
}: {
  items: Monitor[];
  webhooks: Webhook[];
  config: ProductConfig;
  refresh: () => Promise<void>;
  loading: boolean;
}) {
  const [create, setCreate] = useState(false);
  const [history, setHistory] = useState<Monitor | null>(null);
  const active = items.filter((item) => !['cancelled', 'expired'].includes(item.status));
  const observed = active.filter((item) => item.latest);
  const delayed = active.filter((item) => item.stale || item.status === 'degraded');
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">A little peace of mind</span>
          <h1>Your flights, in view.</h1>
          <p>Watch the itinerary you want. Know when its observed price moves.</p>
        </div>
        <Button
          kind="primary"
          onClick={() => setCreate(true)}
          disabled={active.length >= config.limits.monitors}
        >
          <Icon name="plus" size={18} />
          Watch a flight
        </Button>
      </div>
      <div className="stats">
        <div>
          <span>Flight monitors</span>
          <strong>
            {active.length}
            <small> / {config.limits.monitors}</small>
          </strong>
          <p>Your development allowance</p>
        </div>
        <div>
          <span>With a recorded price</span>
          <strong>{observed.length}</strong>
          <p>Actual observations, with timestamps</p>
        </div>
        <div>
          <span>Need a fresh check</span>
          <strong>{delayed.length}</strong>
          <p>{delayed.length ? 'Last prices may have changed' : 'No delayed prices to review'}</p>
        </div>
      </div>
      <div className="section-heading">
        <h2>Flight monitors</h2>
        <span>{loading ? 'Refreshing…' : `${items.length} total`}</span>
      </div>
      {items.length ? (
        <div className="monitor-list">
          {items.map((item) => (
            <MonitorCard
              key={item.id}
              monitor={item}
              refresh={refresh}
              onHistory={() => setHistory(item)}
            />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty title="Start with a flight you have in mind">
            Select your itinerary on Google Flights, copy its link, and add your first monitor. Your
            price history will grow with each successful check.
          </Empty>
          <div className="empty-action">
            <Button kind="primary" onClick={() => setCreate(true)}>
              <Icon name="plus" size={17} />
              Watch your first flight
            </Button>
          </div>
        </div>
      )}
      <p className="page-note">
        <Icon name="shield" size={16} />
        Prices are observed periodically. We cannot guarantee the lowest market price or a fare at
        booking.
      </p>
      {create && (
        <CreateMonitor
          config={config}
          webhooks={webhooks}
          onCreated={refresh}
          onClose={() => setCreate(false)}
        />
      )}
      {history && <History monitor={history} onClose={() => setHistory(null)} />}
    </>
  );
}
