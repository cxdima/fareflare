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
