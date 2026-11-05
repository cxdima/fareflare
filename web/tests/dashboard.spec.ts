import { test, expect, type Page as BrowserPage } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';

const flightUrl =
  'https://www.google.com/travel/flights?tfs=CBoQAho_EgoyMDI3LTAzLTE0Ih8KA0RFThIKMjAyNy0wMy0xNBoDREZXKgJVQTIDNDE0agcIARIDREVOcgcIARIDREZXQAFIAVIDVVNEyAEB&curr=USD&hl=en-US&gl=US&gsas=1';
const now = Math.floor(Date.now() / 1000);
const observation = {
  amount_minor: 24500,
  currency: 'USD',
  observed_at: now - 1800,
  fare_name: 'Economy',
  price_basis: 'total',
  source: 'google_flights',
};
const monitor = {
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

async function mock(page: BrowserPage, signedIn = true) {
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
        monitors.find((value) => path.endsWith(String(value.id)))!,
        body,
      );
      return reply(monitors[0]);
    }
    if (path.endsWith('/policy') && method === 'PUT') {
      monitors[0].policy = body;
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
      webhooks[0].status = 'active';
      return reply(webhooks[0]);
    }
    if (path === '/v1/api-keys' && method === 'GET') return reply({ items: keys });
    if (path === '/v1/api-keys' && method === 'POST') {
      keys.push({ id: 'k'.repeat(64), name: body.name, expires_at: now + 86400, revoked: false });
      return reply({ id: 'k'.repeat(64), api_key: 'once-only-api-key' }, 201);
    }
    if (path.startsWith('/v1/api-keys/') && method === 'DELETE') {
      keys[0].revoked = true;
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

test('sign in, create a monitor with CSRF and idempotency, and keep credentials out of browser storage', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/app');
  await page.getByLabel('Username', { exact: true }).fill('traveler');
  await page.getByLabel('Password', { exact: true }).fill('a-long-private-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toBeVisible();
  await expect(
    page.getByText(/Free during development|Development preview|family commands/i),
  ).toHaveCount(0);
  await expect(page.getByText(/upgrade|payment method|subscribe now/i)).toHaveCount(0);
  await page.getByRole('button', { name: 'Watch your first flight' }).click();
  await page.getByLabel('Google Flights link').fill(flightUrl);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByText('Awaiting first check')).toBeVisible();
  await expect(page.getByText(/check delayed|checks delayed/)).toHaveCount(0);
  const create = calls.find((item) => item.path === '/v1/monitors' && item.method === 'POST')!;
  expect(create.csrf).toBe('csrf-test');
  expect(create.key).toBeTruthy();
  expect(create.body.interval_seconds).toBe(900);
  expect(
    await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
  ).toEqual({ local: 0, session: 0 });
});

test('history shows actual totals and supports pause, resume and stop', async ({ page }) => {
  await mock(page);
  await page.goto('/app');
  await expect(page.getByText('Waiting for an updated price')).toBeVisible();
  await expect(page.locator('[style]')).toHaveCount(0);
  await expect(page.getByText('$245.00', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Price history' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('table')).toBeVisible();
  await expect(dialog.getByRole('img')).toHaveAttribute('aria-label', /\$300.00 to \$245.00/);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Price history' })).toBeFocused();
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(page.getByText('Paused', { exact: true })).toBeVisible();
  await expect(page.getByText(/check delayed|checks delayed/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Resume' }).click();
  await expect(page.getByRole('article').getByText('Watching', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.getByRole('button', { name: 'Stop watching', exact: true }).click();
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible();
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            ...structuredClone(monitor),
            status: 'cancelled',
            collection_status: 'blocked',
            last_error: 'provider_blocked',
          },
        ],
      },
    }),
  );
  await page.reload();
  await expect(
    page.getByText('This monitor is no longer checking prices.', { exact: false }),
  ).toBeVisible();
  await expect(page.getByText('Use Retry collection to try again.', { exact: false })).toHaveCount(
    0,
  );
  await expect(page.getByRole('button', { name: 'Retry collection', exact: true })).toHaveCount(0);
});

test('webhook ownership verification and secrets are explicit', async ({ page }) => {
  const calls = await mock(page);
  await page.goto('/app#webhooks');
  await page.getByLabel('Receiver URL').fill('https://example.com/alerts');
  await page.getByRole('button', { name: 'Add receiver' }).click();
  await expect(
    page.getByRole('textbox', { name: 'Webhook signing secret', exact: true }),
  ).toHaveValue('once-only-webhook-secret');
  await page.getByRole('button', { name: 'I’ve saved it' }).click();
  await page.getByRole('button', { name: 'Send verification challenge' }).click();
  await expect(page.getByText(/Challenge delivered/)).toBeVisible();
  await page.getByLabel('Verification token').fill('receiver-token');
  await page.getByRole('button', { name: 'Verify receiver' }).click();
  await expect(page.getByText('Verified', { exact: true })).toBeVisible();
  expect(calls.find((item) => item.path.endsWith('/verify'))?.body.token).toBe('receiver-token');
  await expect(page.getByText('once-only-webhook-secret')).toHaveCount(0);
});

test('API keys are shown once and revocable, with MCP connection details', async ({ page }) => {
  await mock(page);
  await page.goto('/app#developer');
  await expect(page.getByLabel('Remote MCP server')).toHaveValue('http://127.0.0.1:8007/mcp');
  await page.getByLabel('Key name').fill('My local client');
  await page.getByRole('button', { name: 'Create key' }).click();
  await expect(page.getByRole('textbox', { name: 'Your API key', exact: true })).toHaveValue(
    'once-only-api-key',
  );
  await page.getByRole('link', { name: 'Flight monitors' }).click();
  await page.getByRole('link', { name: 'API & MCP' }).click();
  await expect(page.getByRole('textbox', { name: 'Your API key', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Revoke My local client' }).click();
  await page.getByRole('button', { name: 'Revoke key', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'Revoked', exact: true })).toBeVisible();
});

test('registration keeps OAuth authorization pending until explicit consent', async ({ page }) => {
  await mock(page, false);
  await page.goto('/app?authorize=request-123&invite=invite-test');
  await page.getByLabel('Username', { exact: true }).fill('traveler');
  await page.getByLabel('Password', { exact: true }).fill('a-long-private-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Connect an application' })).toBeVisible();
  await expect(page.getByText('Travel helper', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Allow access' })).toBeVisible();
  await expect(page).toHaveURL(/authorize=request-123/);
  await expect(
    page.getByRole('textbox', { name: 'Your account recovery code', exact: true }),
  ).toHaveValue('once-only-recovery');
});

test('dashboard, dialog, login, and mobile layout pass accessibility checks', async ({ page }) => {
  await mock(page);
  await page.goto('/app');
  await expect(page.getByText('Waiting for an updated price')).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  await expect(page.locator('[style]')).toHaveCount(0);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload();
  await expect(page.getByText('Waiting for an updated price')).toBeVisible();
  await page.screenshot({ path: 'artifacts/dashboard-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.getByText('Waiting for an updated price')).toBeVisible();
  await expect(page.locator('ff-dashboard')).toHaveCount(1);
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toHaveCount(1);
  const mobileLinks = page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link');
  await expect(mobileLinks).toHaveCount(5);
  for (const link of await mobileLinks.all()) {
    const bounds = await link.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(375);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'artifacts/dashboard-mobile-viewport.png' });
  await page.screenshot({ path: 'artifacts/dashboard-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test('actual portal: invitation, cookie session, monitor, API key, recovery and deletion under CSP', async ({
  page,
}, testInfo) => {
  const fixture = JSON.parse(await readFile('artifacts/portal-fixture.json', 'utf8'));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (entry) => {
    if (/Content Security Policy|Refused to/.test(entry.text())) errors.push(entry.text());
  });
  const username = `browsertraveler${testInfo.retry}`;
  await page.goto(`/?invite=${encodeURIComponent(fixture.invites[testInfo.retry])}`);
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill('first-private-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  const recovery = await page
    .getByRole('textbox', { name: 'Your account recovery code', exact: true })
    .inputValue();
  expect(recovery.length).toBeGreaterThan(20);
  expect(await page.evaluate(() => document.cookie)).not.toContain('session');
  await page.getByRole('button', { name: 'Watch your first flight' }).click();
  await page.getByLabel('Google Flights link').fill(flightUrl);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByRole('heading', { name: 'DEN → DFW', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'API & MCP' }).click();
  await page.getByLabel('Key name').fill('Browser test');
  await page.getByRole('button', { name: 'Create key' }).click();
  const key = await page.getByRole('textbox', { name: 'Your API key', exact: true }).inputValue();
  const recoveryField = page.getByRole('textbox', {
    name: 'Your account recovery code',
    exact: true,
  });
  await expect(recoveryField).toHaveValue(recovery);
  expect(await recoveryField.getAttribute('id')).not.toBe(
    await page.getByRole('textbox', { name: 'Your API key', exact: true }).getAttribute('id'),
  );
  await page
    .getByRole('region', { name: 'Your account recovery code', exact: true })
    .getByRole('button', { name: 'I’ve saved it' })
    .click();
  const apiResult = await page.request.get('http://127.0.0.1:8007/v1/monitors', {
    headers: { Authorization: `Bearer ${key}` },
  });
  expect(apiResult.status()).toBe(200);
  expect((await apiResult.json()).items).toHaveLength(1);
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Your API key', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByRole('button', { name: 'Forgot your password?' }).click();
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Recovery code', { exact: true }).fill(recovery);
  await page.getByLabel('New password', { exact: true }).fill('second-private-password');
  await page.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toBeVisible();
  expect(
    (
      await page.request.get('http://127.0.0.1:8007/v1/monitors', {
        headers: { Authorization: `Bearer ${key}` },
      })
    ).status(),
  ).toBe(401);
  await page.getByRole('link', { name: 'Account settings' }).click();
  await page.getByRole('button', { name: 'Delete my account' }).click();
  await page.getByLabel('Confirm password', { exact: true }).fill('second-private-password');
  await page.getByRole('button', { name: 'Permanently delete account' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('a failed create keeps input and reuses its idempotency key on retry', async ({ page }) => {
  await mock(page);
  let attempts = 0;
  const requestKeys: string[] = [];
  await page.route('**/v1/monitors', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    requestKeys.push(route.request().headers()['idempotency-key']);
    if (++attempts === 1)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Service temporarily unavailable. Try again.' }),
      });
    return route.fallback();
  });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  await page.getByLabel('Google Flights link').fill(flightUrl);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByRole('alert')).toContainText('Service temporarily unavailable');
  await expect(page.getByLabel('Google Flights link')).toHaveValue(flightUrl);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(requestKeys).toHaveLength(2);
  expect(requestKeys[0]).toBe(requestKeys[1]);
});

test('edit alerts, retry a failed delivery, mute notifications, and revoke MCP access', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app');
  await page.getByRole('button', { name: 'Edit alerts' }).click();
  await page.getByLabel('Notify me when').selectOption('below_price');
  await page.getByLabel('Target total (USD)').fill('199.95');
  await page.getByRole('button', { name: 'Save alert policy' }).click();
  await expect(page.getByText(/Alert below \$199.95/)).toBeVisible();
  expect(calls.find((item) => item.path.endsWith('/policy'))?.body.threshold_minor).toBe(19995);
  await page.getByRole('link', { name: 'Alert activity' }).click();
  await page.getByRole('button', { name: /Retry delivery/ }).click();
  expect(
    calls.some((item) => item.path === '/v1/alerts/alert/retry' && item.csrf === 'csrf-test'),
  ).toBe(true);
  await page.getByRole('link', { name: 'Account settings' }).click();
  await page.getByLabel('Mute all notifications').check();
  await page.getByLabel('Muted routes', { exact: true }).fill('den-dfw');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await expect(page.getByText('Notification preferences saved.')).toBeVisible();
  expect(
    calls.find((item) => item.path === '/v1/preferences' && item.method === 'PUT')?.body,
  ).toEqual({ muted: true, muted_routes: ['DEN-DFW'] });
  await page.getByRole('button', { name: 'Revoke access for Travel helper' }).click();
  await page.getByRole('button', { name: 'Revoke access', exact: true }).click();
  await expect(page.getByText('No connected applications.')).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test('route-search capability displays the actual matching flight and offer link', async ({
  page,
}) => {
  await mock(page);
  const routeSearch = {
    ...monitor,
    target: {
      ...monitor.target,
      kind: 'search',
      url: 'https://www.google.com/travel/flights?search=route',
      segments: [
        {
          date: '2027-03-14',
          legs: [
            { origin: 'DEN', destination: 'DFW', date: '2027-03-14', airline: null, number: null },
          ],
        },
      ],
    },
    latest: {
      ...observation,
      observed_offer: {
        target_id: 'actual-offer',
        segments: monitor.target.segments,
        adults: 1,
        cabin: 1,
        url: flightUrl,
      },
    },
  };
  await page.route('**/v1/config', (route) =>
    route.fulfill({
      json: {
        product_name: 'Fareflare',
        billing_enabled: false,
        registration_mode: 'invite',
        capabilities: { route_searches: true },
        limits: { monitors: 3, min_interval_seconds: 900 },
      },
    }),
  );
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({ json: { items: [routeSearch] } }),
  );
  await page.goto('/app');
  await expect(page.getByText('Cheapest matching route', { exact: true })).toBeVisible();
  await expect(page.getByText('Latest match: UA 414', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /View flight/ })).toHaveAttribute('href', flightUrl);
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  await page.getByText('Supported flights and searches', { exact: true }).click();
  await expect(page.getByText(/Route searches: exact airports and date/)).toBeVisible();
  await expect(page.getByText(/economy excluding Basic/)).toBeVisible();
});

test('connection setup copies complete URLs and requests without clipping on mobile', async ({
  page,
  context,
}) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await mock(page);
  await page.goto('/app#developer');
  await page.getByRole('button', { name: 'Copy URL', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Copied', exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    'http://127.0.0.1:8007/mcp',
  );
  await page.screenshot({ path: 'artifacts/developer-mcp-desktop.png', fullPage: true });
  await page
    .getByRole('button', { name: 'HTTP API Use your own application', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'Make your first API request' })).toBeVisible();
  await page.getByRole('button', { name: 'Copy request', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    "curl 'http://127.0.0.1:8007/v1/monitors'",
  );
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    'Authorization: Bearer YOUR_API_KEY',
  );
  await page.screenshot({ path: 'artifacts/developer-api-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.getByLabel('Remote MCP server')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'artifacts/developer-mcp-mobile.png', fullPage: true });
  await page
    .getByRole('button', { name: 'HTTP API Use your own application', exact: true })
    .click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'artifacts/developer-api-mobile.png', fullPage: true });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.evaluate(() => {
    Object.defineProperty(navigator.clipboard, 'writeText', {
      value: () => Promise.reject(new Error('denied')),
      configurable: true,
    });
  });
  await page.getByRole('button', { name: 'Copy request', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText(
    'Copy is unavailable. Select the text and copy it manually.',
  );
});

test('airline identity has readable fallbacks for missing artwork and unknown carriers', async ({
  page,
}) => {
  await mock(page);
  await page.route('**/assets/airlines/UA.png', (route) => route.abort());
  await page.goto('/app');
  await expect(page.getByText('United Airlines', { exact: true })).toBeVisible();
  await expect(page.locator('ff-airline img')).toHaveCount(0);
  const unknown = structuredClone(monitor);
  unknown.target.segments[0].legs[0].airline = 'ZZ';
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({ json: { items: [unknown] } }),
  );
  await page.reload();
  await expect(page.locator('ff-airline').getByText('ZZ', { exact: true }).last()).toBeVisible();
  await expect(page.locator('ff-airline img')).toHaveCount(0);
  await expect(page.getByText('ZZ 414', { exact: true })).toBeVisible();
});
