import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile, readdir } from 'node:fs/promises';

import { mock, monitor, flightUrl, observation } from './fixtures';

test('sign in, create a monitor with CSRF and idempotency, and keep credentials out of browser storage', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/app');
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
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
  const manage = page.getByText('Manage flight', { exact: true });
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeHidden();
  await manage.focus();
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(page.getByRole('article').getByText('Paused', { exact: true })).toBeVisible();
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
  await page.getByText('Create an API key', { exact: true }).click();
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
  await expect(page).toHaveURL(/\/register\?authorize=request-123/);
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
  await page.getByLabel('Password', { exact: true }).fill('a-long-private-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Connect an application' })).toBeVisible();
  await expect(page.getByText('Travel helper', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Allow access' })).toBeVisible();
  await expect(page).toHaveURL(/authorize=request-123/);
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

/** The newest account email to an address, and the token from its link. */
async function emailedToken(address: string, subject: RegExp): Promise<string> {
  for (let attempt = 0; attempt < 20; attempt++) {
    const names = (await readdir('artifacts/outbox').catch(() => [] as string[])).sort().reverse();
    for (const name of names) {
      const text = await readFile(`artifacts/outbox/${name}`, 'utf8');
      if (!text.includes(`To: ${address}`) || !subject.test(text)) continue;
      const token = /#token=([A-Za-z0-9_-]{43})/.exec(text);
      if (token) return token[1];
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`No email to ${address}`);
}

test('actual portal: sign-up, email confirmation, password reset by email, keys and deletion under CSP', async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (entry) => {
    if (/Content Security Policy|Refused to/.test(entry.text())) errors.push(entry.text());
  });
  const username = `browsertraveler${testInfo.retry}-${Date.now()}@example.com`;
  const keyHeader = (key: string) => ({ headers: { Authorization: `Bearer ${key}` } });
  await page.goto('/register');
  await page.getByLabel('Email', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill('first-private-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(await page.evaluate(() => document.cookie)).not.toContain('session');
  await page.getByRole('button', { name: 'Watch your first flight' }).click();
  await page.getByLabel('Google Flights link').fill(flightUrl);
  await page.getByRole('button', { name: 'Start watching' }).click();
  await expect(page.getByRole('heading', { name: 'DEN → DFW', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'API & MCP' }).click();
  await page.getByText('Create an API key', { exact: true }).click();
  await page.getByLabel('Key name').fill('Browser test');
  await page.getByRole('button', { name: 'Create key' }).click();
  const key = await page.getByRole('textbox', { name: 'Your API key', exact: true }).inputValue();
  const apiResult = await page.request.get('http://127.0.0.1:8007/v1/monitors', keyHeader(key));
  expect(apiResult.status()).toBe(200);
  expect((await apiResult.json()).items).toHaveLength(1);
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Your API key', exact: true })).toHaveCount(0);

  // A password manager asking where passwords are changed lands on the right section.
  await page.goto('/.well-known/change-password');
  await expect(page).toHaveURL('/app#settings?section=security');
  await expect(page.locator('.security-address')).toHaveText(username);
  await expect(page.locator('.security-value .status').first()).toHaveText('Not confirmed');

  // The confirmation email's link confirms the address.
  await page.goto(`/confirm-email#token=${await emailedToken(username, /Subject: Confirm/)}`);
  await expect(page.getByRole('heading', { name: 'Email confirmed', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Go to your flights' }).click();
  await page.goto('/app#settings?section=security');
  await expect(page.locator('.security-value .status').first()).toHaveText('Confirmed');

  await page.locator('[aria-controls="password-drawer"]').click();
  const current = page.getByLabel('Current password', { exact: true });
  await current.fill('not-the-right-password');
  await page.getByLabel('New password', { exact: true }).fill('changed-private-password');
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  // A mistyped password is an error on this page, not the end of the session.
  await expect(page.locator('#password-drawer').getByRole('alert')).toHaveText(
    'That password is not correct',
  );
  await current.fill('first-private-password');
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await expect(page.getByText(/Password changed/)).toBeVisible();

  // Forgotten: a reset link arrives by email, and the new password signs straight in.
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await page.getByLabel('Email', { exact: true }).fill(username.toUpperCase());
  await page.getByLabel('Password', { exact: true }).fill('first-private-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Incorrect email or password');
  await page.getByRole('button', { name: 'Forgot password?' }).click();
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue(username.toUpperCase());
  await page.getByRole('button', { name: 'Email me a reset link' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible();
  await page.goto(`/reset-password#token=${await emailedToken(username, /Subject: Reset/)}`);
  await expect(page.locator('input[autocomplete="username"]')).toHaveValue(username);
  await page.getByLabel('New password', { exact: true }).fill('second-private-password');
  await page.getByRole('button', { name: 'Save and sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toBeVisible();
  // A reset is not a revocation: the key keeps working until signed out everywhere.
  expect(
    (await page.request.get('http://127.0.0.1:8007/v1/monitors', keyHeader(key))).status(),
  ).toBe(200);

  await page.goto('/app#settings?section=security');
  await page.locator('[aria-controls="everywhere-drawer"]').click();
  await page.locator('#everywhere-password').fill('second-private-password');
  await page
    .locator('#everywhere-drawer')
    .getByRole('button', { name: 'Sign out everywhere' })
    .click();
  await expect(page.getByText(/Every other browser is signed out/)).toBeVisible();
  expect(
    (await page.request.get('http://127.0.0.1:8007/v1/monitors', keyHeader(key))).status(),
  ).toBe(401);

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
  await page.getByText('Manage flight', { exact: true }).click();
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
  await page.getByRole('button', { name: 'Notifications', exact: true }).click();
  await page.getByLabel('Mute all notifications').check();
  await page.getByLabel('Muted routes', { exact: true }).fill('den-dfw');
  await page.getByRole('button', { name: 'Save preferences' }).click();
  await expect(page.getByText('Notification preferences saved.')).toBeVisible();
  expect(
    calls.find((item) => item.path === '/v1/preferences' && item.method === 'PUT')?.body,
  ).toEqual({ muted: true, muted_routes: ['DEN-DFW'] });
  await page.getByRole('button', { name: 'Connections', exact: true }).click();
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
        registration_mode: 'open',
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

test('the first mobile fare is visible without opening filters or management controls', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await mock(page);
  await page.goto('/app');
  await expect(page.getByText('$245.00', { exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByLabel('Find a flight')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeHidden();
  const airline = page.locator('ff-airline').first();
  const mark = await airline.locator('.airline-mark').boundingBox();
  const name = await airline.getByText('United Airlines', { exact: true }).boundingBox();
  expect(mark).not.toBeNull();
  expect(name).not.toBeNull();
  expect(mark!.width).toBeLessThanOrEqual(32);
  expect(mark!.height).toBeLessThanOrEqual(32);
  expect(name!.x - mark!.x - mark!.width).toBeGreaterThanOrEqual(6);
  expect(name!.x - mark!.x - mark!.width).toBeLessThanOrEqual(12);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('collection and delivery choices survive collapsing their disclosure before saving', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.route(/\/v1\/webhooks(?:\?|$)/, (route) =>
    route.fulfill({
      json: {
        items: [{ id: 'receiver', url: 'https://example.com/prices', status: 'active' }],
      },
    }),
  );
  await page.goto('/app');
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  await expect(page.getByLabel('Google Flights link')).toBeVisible();
  await expect(page.getByLabel('Check interval')).toBeHidden();
  await page.getByLabel('Google Flights link').fill(flightUrl);
  const options = page.getByText('Check frequency and alert destination', { exact: true });
  await options.focus();
  await page.keyboard.press('Enter');
  await page.getByLabel('Check interval').selectOption('1800');
  await page.getByLabel('Alert destination').selectOption('receiver');
  await options.click();
  await expect(page.getByLabel('Check interval')).toBeHidden();
  await page.getByRole('button', { name: 'Start watching', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const creation = calls.find((call) => call.path === '/v1/monitors' && call.method === 'POST');
  expect(creation?.body.interval_seconds).toBe(1800);
  expect(creation?.body.webhook_id).toBe('receiver');
});
