import type { Page as BrowserPage } from '@playwright/test';

export const flightUrl =
  'https://www.google.com/travel/flights?tfs=CBoQAho_EgoyMDI3LTAzLTE0Ih8KA0RFThIKMjAyNy0wMy0xNBoDREZXKgJVQTIDNDE0agcIARIDREVOcgcIARIDREZXQAFIAVIDVVNEyAEB&curr=USD&hl=en-US&gl=US&gsas=1';
export const now = Math.floor(Date.now() / 1000);
export const observation = {
  amount_minor: 24500,
  currency: 'USD',
  observed_at: now - 1800,
  fare_name: 'Economy',
  price_basis: 'total',
  source: 'google_flights',
};
export const monitor = {
  id: 'a'.repeat(32),
  status: 'active',
  target: {
    segments: [
      {
        date: '2027-03-14',
        legs: [
          { origin: 'DEN', destination: 'DFW', airline: 'UA', number: '414', date: '2027-03-14' },
        ],
      },
    ],
    adults: 1,
    currency: 'USD',
    url: flightUrl,
  },
  interval_seconds: 900,
  latest: observation,
  stale: true,
  last_error: null,
  collection_status: 'ready',
  next_check_at: now + 60,
  webhook_id: null,
  policy: { kind: 'new_low', min_drop_minor: 0, threshold_minor: null, notify_rebounds: false },
};

export async function mock(page: BrowserPage, signedIn = true) {
  const monitors: Record<string, unknown>[] = signedIn ? [structuredClone(monitor)] : [];
  const webhooks: Record<string, unknown>[] = [];
  const keys: Record<string, unknown>[] = [];
  const grants = [
    {
      id: 'grant-1',
      client_name: 'Travel helper',
      created_at: now,
      expires_at: now + 86400,
      revoked: false,
    },
  ];
  const calls: { path: string; method: string; body: any; csrf?: string; key?: string }[] = [];
  await page.route(/\/(?:v1|auth)\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postDataJSON();
    calls.push({
      path,
      method,
      body,
      csrf: request.headers()['x-csrf-token'],
      key: request.headers()['idempotency-key'],
    });
    const reply = (value: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    if (path === '/v1/config')
      return reply({
        product_name: 'Fareflare',
        billing_enabled: false,
        registration_mode: 'invite',
        limits: { monitors: 3, min_interval_seconds: 900 },
      });
    if (path === '/v1/account' && method === 'GET')
      return signedIn
        ? reply({ account: { id: 'user', username: 'traveler' }, csrf_token: 'csrf-test' })
        : reply({ detail: 'Sign in' }, 401);
    if (path === '/auth/password') return reply({ changed: true });
    if (path === '/auth/recovery-code') return reply({ recovery_code: 'replacement-recovery' });
    if (path.startsWith('/auth/')) {
      signedIn = path !== '/auth/logout';
      return reply({
        account: { id: 'user', username: body?.username ?? 'traveler' },
        csrf_token: 'csrf-test',
        ...(path !== '/auth/login' && path !== '/auth/logout'
          ? { recovery_code: 'once-only-recovery' }
          : {}),
      });
    }
    if (path === '/v1/monitors' && method === 'GET') return reply({ items: monitors });
    if (path === '/v1/monitors' && method === 'POST') {
      const value = {
        ...structuredClone(monitor),
        id: 'b'.repeat(32),
        status: 'pending',
        latest: null,
        stale: false,
      };
      monitors.push(value);
      return reply(value, 202);
    }
    if (path.endsWith('/history'))
      return reply({
        items: [observation, { ...observation, amount_minor: 30000, observed_at: now - 5400 }],
      });
    if (path.startsWith('/v1/monitors/') && method === 'PATCH') {
      Object.assign(
        monitors.find((value) => path.endsWith(String(value['id'])))!,
        body,
      );
      return reply(monitors[0]);
    }
    if (path.endsWith('/policy') && method === 'PUT') {
      monitors[0]['policy'] = body;
      return reply(monitors[0]);
    }
    if (path === '/v1/webhooks' && method === 'GET') return reply({ items: webhooks });
    if (path === '/v1/webhooks' && method === 'POST') {
      const value = {
        id: 'c'.repeat(32),
        url: body.url,
        status: 'pending',
        created_at: now,
        verified_at: null,
      };
      webhooks.push(value);
      return reply({ ...value, signing_secret: 'once-only-webhook-secret' }, 201);
    }
    if (path.endsWith('/challenge')) return reply({ delivered: true, expires_at: now + 300 });
    if (path.endsWith('/verify')) {
      webhooks[0]['status'] = 'active';
      return reply(webhooks[0]);
    }
    if (path === '/v1/api-keys' && method === 'GET') return reply({ items: keys });
    if (path === '/v1/api-keys' && method === 'POST') {
      keys.push({ id: 'k'.repeat(64), name: body.name, expires_at: now + 86400, revoked: false });
      return reply({ id: 'k'.repeat(64), api_key: 'once-only-api-key' }, 201);
    }
    if (path.startsWith('/v1/api-keys/') && method === 'DELETE') {
      keys[0]['revoked'] = true;
      return reply({ revoked: true });
    }
    if (path === '/v1/alerts')
      return reply({
        items: [
          {
            id: 'alert',
            monitor_id: monitor.id,
            reason: 'new_low',
            status: 'dead_letter',
            attempts: 5,
            observation,
            webhook_id: 'webhook',
          },
        ],
      });
    if (path === '/v1/preferences')
      return reply(method === 'GET' ? { muted: false, muted_routes: [] } : body);
    if (path === '/v1/telegram') return reply({ enabled: false, connected: false });
    if (path === '/v1/oauth/grants') return reply({ items: grants });
    if (path.startsWith('/v1/oauth/grants/') && method === 'DELETE') {
      grants[0].revoked = true;
      return reply({ revoked: true });
    }
    if (path.startsWith('/v1/oauth/requests/'))
      return reply({
        client_name: 'Travel helper',
        client_id: 'known-client',
        resource: 'https://fareflare.example/mcp',
        scopes: ['mcp:tools'],
        redirect_uri: 'https://client.example/callback',
      });
    return reply({ ok: true });
  });
  return calls;
}
