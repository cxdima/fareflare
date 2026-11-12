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
  const backupCodes = ['ab2c-de3f', 'gh4j-km5n', 'pq6r-st7u', 'vw8x-yz9a', 'b2cd-3efg'];
  const passkeyOptions = {
    challenge: 'Y2hhbGxlbmdl',
    rp: { id: '127.0.0.1', name: 'Fareflare' },
    user: { id: 'dXNlcg', name: 'traveler@example.com', displayName: 'traveler@example.com' },
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
    timeout: 300000,
    excludeCredentials: [],
    authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
    attestation: 'none',
    allowCredentials: [],
    userVerification: 'required',
  };
  const security = {
    email: 'traveler@example.com',
    email_verified: true,
    email_enabled: true,
    two_factor: { enabled: false, backup_codes_left: 0, enabled_at: null as number | null },
    passkeys: [] as {
      id: string;
      credential_id: string;
      name: string;
      provider: string;
      synced: boolean;
      created_at: number;
      last_used_at: number | null;
    }[],
  };
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
        registration_mode: 'open',
        email_enabled: true,
        limits: { monitors: 3, min_interval_seconds: 900 },
      });
    const account = () => ({
      id: 'user',
      username: security.email,
      email: security.email,
      email_verified: security.email_verified,
    });
    if (path === '/v1/account' && method === 'GET')
      return signedIn
        ? reply({ account: account(), csrf_token: 'csrf-test' })
        : reply({ detail: 'Sign in' }, 401);
    if (path === '/v1/account/security') return reply(security);
    if (path === '/auth/password') return reply({ changed: true });
    if (path === '/auth/login' && body?.password === 'a two-step password')
      return reply({ two_factor_required: true, token: 'two-step-token', expires_at: now + 300 });
    if (path === '/auth/login/two-factor' && body?.code !== '123456')
      return reply({ detail: 'That code is not correct' }, 401);
    if (path === '/auth/password-reset') return reply({ sent: true }, 202);
    if (path === '/auth/password-reset/check')
      return body?.token === 'expired-token'
        ? reply({ detail: 'This reset link is no longer valid. Ask for a new one.' }, 422)
        : reply({ email: 'traveler@example.com', two_factor: body?.token === 'two-step-token' });
    if (path === '/auth/email/confirm')
      return reply({ confirmed: true, email: 'traveler@example.com' });
    if (path === '/auth/email/resend') return reply({ sent: true }, 202);
    if (path === '/auth/email') {
      Object.assign(security, { email: body.email, email_verified: false });
      return reply({ account: account() });
    }
    if (path === '/auth/two-factor/setup')
      return reply({
        secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
        uri: 'otpauth://totp/Fareflare:traveler%40example.com?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=Fareflare',
        account: 'traveler@example.com',
        issuer: 'Fareflare',
      });
    if (path === '/auth/two-factor/enable') {
      if (body?.code !== '123456') return reply({ detail: 'That code is not correct' }, 403);
      security.two_factor = { enabled: true, backup_codes_left: 10, enabled_at: now };
      return reply({ backup_codes: backupCodes });
    }
    if (path === '/auth/two-factor/backup-codes') return reply({ backup_codes: backupCodes });
    if (path === '/auth/two-factor/disable') {
      security.two_factor = { enabled: false, backup_codes_left: 0, enabled_at: null };
      return reply({ enabled: false });
    }
    if (path === '/auth/passkeys/options' || path === '/auth/passkey/options')
      return reply({ challenge_id: 'challenge-test', options: passkeyOptions });
    if (path === '/auth/passkeys' && method === 'POST') {
      const added = {
        id: String(security.passkeys.length + 1).repeat(64),
        credential_id: 'Y3JlZGVudGlhbA',
        name: '1Password',
        provider: '1Password',
        synced: true,
        created_at: now,
        last_used_at: null,
      };
      security.passkeys.push(added);
      return reply(added, 201);
    }
    if (path.startsWith('/auth/passkeys/') && method === 'PATCH') {
      const found = security.passkeys.find((item) => path.endsWith(item.id))!;
      found.name = body.name;
      return reply(found);
    }
    if (path.startsWith('/auth/passkeys/') && method === 'DELETE') {
      security.passkeys = security.passkeys.filter((item) => !path.endsWith(item.id));
      return reply({ removed: true });
    }
    if (path.startsWith('/auth/')) {
      signedIn = path !== '/auth/logout';
      if (path === '/auth/register') security.email = body.email;
      return reply({ account: account(), csrf_token: 'csrf-test' });
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
    if (path === '/v1/status')
      return reply({
        status: 'operational',
        updated_at: now,
        window_hours: 24,
        components: [
          { id: 'website', status: 'operational', reason: null },
          {
            id: 'price_checks',
            status: 'operational',
            reason: null,
            last_run_at: now - 40,
            checks: 96,
            succeeded: 90,
          },
          { id: 'alerts', status: 'operational', reason: null, sent: 2 },
        ],
        hours: [],
      });
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

/**
 * Stands in for the browser's passkey prompt. Real WebAuthn needs a domain name,
 * and these tests run on 127.0.0.1; the service's own tests verify real signatures.
 */
export async function fakePasskeys(page: BrowserPage, { autofill = false } = {}) {
  await page.addInitScript((offerAutofill) => {
    const bytes = (text: string) => new TextEncoder().encode(text).buffer;
    const calls: { kind: string; mediation?: string }[] = [];
    (window as unknown as { passkeyCalls: typeof calls }).passkeyCalls = calls;
    Object.defineProperty(PublicKeyCredential, 'isConditionalMediationAvailable', {
      value: async () => offerAutofill,
    });
    const common = {
      id: 'Y3JlZGVudGlhbA',
      rawId: bytes('credential'),
      type: 'public-key',
      authenticatorAttachment: 'platform',
      getClientExtensionResults: () => ({}),
    };
    navigator.credentials.create = (async () => {
      calls.push({ kind: 'create' });
      return {
        ...common,
        response: {
          clientDataJSON: bytes('{}'),
          attestationObject: bytes('attestation'),
          getTransports: () => ['internal', 'hybrid'],
        },
      };
    }) as unknown as typeof navigator.credentials.create;
    navigator.credentials.get = (async (options?: CredentialRequestOptions) => {
      calls.push({ kind: 'get', mediation: options?.mediation });
      return {
        ...common,
        response: {
          clientDataJSON: bytes('{}'),
          authenticatorData: bytes('data'),
          signature: bytes('signature'),
          userHandle: bytes('user'),
        },
      };
    }) as unknown as typeof navigator.credentials.get;
  }, autofill);
}

/**
 * The admin API, layered over `mock`: Playwright runs the newest route first, and
 * anything this layer does not answer falls through to the ordinary mock.
 */
export async function mockAdmin(
  page: BrowserPage,
  {
    gate = 'ready',
    mustChange = false,
  }: { gate?: 'ready' | 'mfa' | 'reauth'; mustChange?: boolean } = {},
) {
  const calls: { path: string; method: string; body: any; csrf?: string }[] = [];
  let changing = mustChange;
  const switches = { registration_paused: false, collection_paused: false };
  const alice = {
    id: 'acct_' + 'a'.repeat(32),
    email: 'alice@example.com',
    status: 'active',
    admin: false,
    created_at: now - 3 * 86400,
    last_sign_in_at: now - 600,
    email_verified: true,
    two_factor: true,
    passkeys: 1,
    api_keys: 1,
    flights: 1,
    telegram: true,
    must_change_password: false,
    suspended_at: null as number | null,
  };
  const users = [
    alice,
    {
      ...alice,
      id: 'acct_' + 'b'.repeat(32),
      email: 'bob@example.com',
      created_at: now - 86400,
      last_sign_in_at: null,
      email_verified: false,
      two_factor: false,
      passkeys: 0,
      api_keys: 0,
      flights: 0,
      telegram: false,
    },
  ];
  const audit: {
    at: number;
    action: string;
    admin_id: string;
    admin: string;
    target_id: string | null;
    target: string | null;
    detail: Record<string, unknown>;
  }[] = [
    {
      at: now - 7200,
      action: 'stop-flight',
      admin_id: 'acct_admin',
      admin: 'admin@fareflare.dev',
      target_id: alice.id,
      target: alice.email,
      detail: { route: 'DEN → DFW', reason: 'Duplicate' },
    },
    {
      at: now - 9000,
      action: 'switches',
      admin_id: 'acct_admin',
      admin: 'admin@fareflare.dev',
      target_id: null,
      target: null,
      detail: { collection_paused: false },
    },
  ];
  const hours = Array.from({ length: 24 }, (_, index) => ({
    start: now - (23 - index) * 3600,
    runs: index < 3 ? 0 : 12,
    collected: index < 3 ? 0 : 11,
    failed: index < 3 ? 0 : index === 10 ? 6 : 1,
    alerts_sent: index % 5 === 0 ? 1 : 0,
    status: index < 3 ? 'none' : index === 10 ? 'degraded' : 'operational',
  }));
  await page.route(/\/(?:v1|auth)\//, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const body = request.postDataJSON();
    const reply = (value: unknown, status = 200) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    if (path === '/v1/account' && method === 'GET')
      return reply({
        account: {
          id: 'acct_admin',
          username: 'admin@fareflare.dev',
          email: 'admin@fareflare.dev',
          email_verified: false,
          admin: true,
          must_change_password: changing,
        },
        csrf_token: 'csrf-test',
      });
    if (path === '/auth/password' && method === 'POST') {
      calls.push({ path, method, body, csrf: request.headers()['x-csrf-token'] });
      if (body?.current_password !== '123')
        return reply({ detail: 'That password is not correct' }, 403);
      changing = false;
      return reply({ changed: true });
    }
    if (!path.startsWith('/v1/admin/')) return route.fallback();
    calls.push({ path, method, body, csrf: request.headers()['x-csrf-token'] });
    if (path === '/v1/admin/gate')
      return reply(
        gate === 'ready'
          ? { ready: true, reason: null, message: null, expires_at: now + 6 * 3600 }
          : { ready: false, reason: gate, message: 'Not yet', expires_at: null },
      );
    if (path === '/v1/admin/overview')
      return reply({
        generated_at: now,
        users: {
          total: 29,
          active: 27,
          suspended: 1,
          deleted: 6,
          admins: 1,
          new_day: 2,
          new_week: 6,
          new_month: 19,
          signed_in_week: 11,
          signed_in_month: 21,
          email_verified: 14,
          two_factor: 4,
          passkeys: 3,
          telegram: 5,
          api_keys: 2,
          truncated: false,
        },
        signups: Array.from({ length: 30 }, (_, index) => ({
          day: now - (29 - index) * 86400,
          count: [0, 1, 3, 0, 2, 5, 1][index % 7],
        })),
        flights: {
          watched: 6,
          by_status: { active: 4, pending: 1, paused: 1 },
          targets: { collecting: 4, blocked: 1, idle: 0 },
          capacity: { used: 5, limit: 20 },
        },
        collection: {
          status: 'operational',
          updated_at: now,
          window_hours: 24,
          components: [
            { id: 'price_checks', status: 'operational', reason: null, last_run_at: now - 50 },
          ],
          hours,
        },
        email: {
          confirm: { hour: { used: 2, limit: 60 }, day: { used: 9, limit: 300 } },
          reset: { hour: { used: 0, limit: 60 }, day: { used: 1, limit: 300 } },
          notice: { hour: { used: 60, limit: 60 }, day: { used: 60, limit: 300 } },
        },
        switches,
        config: {
          registration_mode: 'open',
          email_enabled: true,
          breach_check: true,
          monitor_limit: 20,
          global_target_limit: 20,
          min_interval_seconds: 900,
        },
      });
    if (path === '/v1/admin/users' && method === 'GET') {
      const query = new URL(request.url()).searchParams.get('q') ?? '';
      const items = users.filter((user) => user.email.includes(query.toLowerCase()));
      return reply({ items, total: items.length, offset: 0, limit: 50, truncated: false });
    }
    const person = users.find((user) => path.startsWith(`/v1/admin/users/${user.id}`));
    if (person && method === 'GET')
      return reply({
        account: {
          ...person,
          sessions: 2,
          suspended_reason: person.status === 'suspended' ? 'Card testing' : null,
          temporary_password_expires_at: null,
          alerts_muted: false,
        },
        flights: person === alice ? [structuredClone(monitor)] : [],
        alerts: [
          {
            id: 'alert-1',
            monitor_id: monitor.id,
            reason: 'new_low',
            status: 'sent',
            attempts: 1,
            observed_at: now - 1800,
            amount_minor: 24500,
            currency: 'USD',
          },
        ],
        api_keys: [
          {
            name: 'Spreadsheet sync',
            created_at: now - 86400,
            expires_at: now + 86400 * 60,
            revoked: false,
          },
        ],
        passkeys: [
          {
            name: '1Password',
            provider: '1Password',
            created_at: now - 86400,
            last_used_at: now - 600,
          },
        ],
        applications: [{ client_name: 'Travel helper', created_at: now - 86400, revoked: false }],
        webhooks: [{ host: 'hooks.example.com', status: 'active', created_at: now - 86400 }],
        audit: audit.filter((entry) => entry.target_id === person.id),
      });
    if (person && method === 'POST') {
      const action = path.split('/').pop();
      if (action === 'suspend') Object.assign(person, { status: 'suspended', suspended_at: now });
      if (action === 'reactivate') Object.assign(person, { status: 'active', suspended_at: null });
      if (action === 'reset-two-factor') person.two_factor = false;
      audit.unshift({
        at: now,
        action: action!,
        admin_id: 'acct_admin',
        admin: 'admin@fareflare.dev',
        target_id: person.id,
        target: person.email,
        detail: body?.reason ? { reason: body.reason } : {},
      });
      return reply(
        action === 'temporary-password'
          ? { done: true, temporary_password: 'Tq9-x2Lm4Zp8', expires_at: now + 86400 }
          : { done: true },
      );
    }
    if (person && method === 'DELETE') {
      if (body?.confirm !== person.email)
        return reply({ detail: "Type the account's email address to confirm." }, 422);
      person.status = 'deleted';
      return reply({ deleted: true });
    }
    if (person && method === 'PATCH')
      return reply({ ...structuredClone(monitor), status: body.status });
    if (path === '/v1/admin/flights')
      return reply({
        items: [
          {
            id: 'target-1',
            state: 'collecting',
            target: monitor.target,
            latest: observation,
            failures: 0,
            last_error: null,
            next_check_at: now + 600,
            interval_seconds: 900,
            watcher_count: 2,
            watchers: [
              {
                monitor_id: monitor.id,
                account_id: alice.id,
                email: alice.email,
                status: 'active',
                interval_seconds: 900,
                created_at: now - 86400,
              },
              {
                monitor_id: 'b'.repeat(32),
                account_id: users[1].id,
                email: users[1].email,
                status: 'paused',
                interval_seconds: 900,
                created_at: now - 3600,
              },
            ],
          },
        ],
        capacity: { used: 5, limit: 20 },
        expired: 3,
      });
    if (path === '/v1/admin/audit') return reply({ items: audit, next_cursor: null });
    if (path === '/v1/admin/switches') {
      Object.assign(switches, body);
      audit.unshift({
        at: now,
        action: 'switches',
        admin_id: 'acct_admin',
        admin: 'admin@fareflare.dev',
        target_id: null,
        target: null,
        detail: body,
      });
      return reply(switches);
    }
    return reply({ detail: 'Not found' }, 404);
  });
  return calls;
}
