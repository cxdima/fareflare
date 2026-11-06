import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { mock, monitor, observation } from './fixtures';
import type { Preferences } from '../src/app/core/types';

test.use({ timezoneId: 'America/Chicago' });

const defaults: Preferences = {
  muted: false,
  muted_routes: [],
  time_zone: null,
  locale: 'en-US',
  hour_cycle: 'auto',
  telegram_style: 'detailed',
  telegram_show_flight_numbers: true,
  telegram_show_observed_time: true,
  telegram_show_fare: true,
  telegram_silent: false,
};

async function preferencesMock(page: Page, initial: Partial<Preferences> = {}) {
  await mock(page);
  let value = { ...defaults, ...initial };
  const writes: Partial<Preferences>[] = [];
  await page.route('**/v1/preferences', (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON();
      writes.push(body);
      value = { ...value, ...body };
    }
    return route.fulfill({ json: value });
  });
  return { writes, value: () => value };
}

test('actual account preferences persist and preview does not save or send', async ({
  page,
}, info) => {
  const fixture = JSON.parse(await readFile('artifacts/portal-fixture.json', 'utf8'));
  await page.goto(`/?invite=${encodeURIComponent(fixture.preferences_invites[info.retry])}`);
  const password = 'private-preferences-test-password';
  await page.getByLabel('Username', { exact: true }).fill(`preferencesuser${info.retry}`);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await page.getByRole('button', { name: 'I’ve saved it' }).click();
  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('America/Chicago');
  await page.getByLabel('Time zone', { exact: true }).fill('Asia/Tokyo');
  await page.getByLabel('Regional format', { exact: true }).selectOption('de-DE');
  await page.getByLabel('Clock', { exact: true }).selectOption('h23');
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  let saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved).toMatchObject({
    time_zone: 'Asia/Tokyo',
    locale: 'de-DE',
    hour_cycle: 'h23',
    muted: false,
  });
  await page.reload();
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('Asia/Tokyo');
  await expect(page.getByLabel('Clock', { exact: true })).toHaveValue('h23');
  await page.getByLabel('Message style').selectOption('compact');
  await page.getByLabel('Flight numbers', { exact: true }).uncheck();
  await page.getByLabel('Fare name', { exact: true }).uncheck();
  await page.getByLabel('Send silently', { exact: true }).check();
  await page.getByRole('button', { name: 'Preview message' }).click();
  const preview = page.locator('.telegram-preview pre');
  await expect(preview).toContainText('Example alert');
  await expect(preview).toContainText('USD 191,00');
  await expect(preview).toContainText('Asia/Tokyo (UTC+09:00)');
  await expect(preview).not.toContainText('UA414');
  await expect(preview).not.toContainText('Fare:');
  const exampleButtons = page.getByRole('group', { name: 'Example Telegram buttons' });
  await expect(exampleButtons).toContainText('View flight');
  await expect(exampleButtons).toContainText('Open Fareflare');
  await expect(exampleButtons.getByRole('link')).toHaveCount(0);
  saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved.telegram_style).toBe('detailed');
  expect(saved.telegram_silent).toBe(false);
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  await page.getByLabel('Mute all notifications').check();
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
  await expect(page.getByText('Notification preferences saved.')).toBeVisible();
  saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved).toMatchObject({
    time_zone: 'Asia/Tokyo',
    telegram_style: 'compact',
    telegram_silent: true,
    telegram_show_flight_numbers: false,
    telegram_show_fare: false,
    muted: true,
  });
  await page.getByRole('button', { name: 'Delete my account' }).click();
  await page.getByLabel('Confirm password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Permanently delete account' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
});

test('regional choices update observations and prices but preserve flight departure dates', async ({
  page,
}) => {
  const state = await preferencesMock(page, {
    time_zone: 'America/Los_Angeles',
    locale: 'en-GB',
    hour_cycle: 'h23',
  });
  const reading = { ...observation, observed_at: Date.parse('2026-11-01T06:30:00Z') / 1000 };
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({ json: { items: [{ ...monitor, latest: reading }], active_count: 1 } }),
  );
  await page.goto('/app');
  await expect(page.locator('.ticket-observation')).toContainText('31 Oct 2026, 23:30');
  await expect(page.locator('.ticket-date')).toHaveText('14 Mar 2027');
  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await page.getByLabel('Time zone', { exact: true }).fill('America/Chicago');
  await page.getByLabel('Regional format', { exact: true }).selectOption('de-DE');
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  expect(state.writes).toEqual([
    { time_zone: 'America/Chicago', locale: 'de-DE', hour_cycle: 'h23' },
  ]);
  await page.getByRole('link', { name: 'Flight monitors', exact: true }).click();
  await expect(page.locator('.ticket-observation')).toContainText('01:30');
  await expect(page.locator('.ticket-observation')).toContainText('Nov. 2026');
  await expect(page.locator('.ticket-price strong')).toHaveText(/245,00\s*\$/);
  await expect(page.locator('.ticket-date')).toContainText('14. März 2027');
  await page.reload();
  await expect(page.locator('.ticket-observation')).toContainText('01:30');
});

test('settings load failures can retry and invalid time zones never reach the API', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  const writes: unknown[] = [];
  await page.route('**/v1/preferences', (route) => {
    if (route.request().method() === 'PUT') writes.push(route.request().postDataJSON());
    return ++attempts === 1
      ? route.fulfill({ status: 503, json: { detail: 'Preferences are temporarily unavailable.' } })
      : route.fulfill({ json: defaults });
  });
  await page.goto('/app#settings');
  await expect(page.getByRole('alert')).toContainText('Preferences are temporarily unavailable.');
  await page.getByRole('button', { name: 'Retry settings' }).click();
  await page.getByLabel('Time zone', { exact: true }).fill('Mars/Olympus');
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Choose a named time zone, such as America/Chicago.')).toBeVisible();
  await expect(page.getByLabel('Time zone', { exact: true })).toBeFocused();
  expect(writes).toEqual([]);
  await page.getByRole('button', { name: 'Use device time zone' }).click();
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('America/Chicago');
});

test('pending saves protect draft edits and failed saves retain input for retry', async ({
  page,
}) => {
  await mock(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let attempts = 0;
  await page.route('**/v1/preferences', async (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: defaults });
    if (++attempts === 1) {
      await gate;
      return route.fulfill({ status: 503, json: { detail: 'Settings could not save.' } });
    }
    return route.fulfill({ json: { ...defaults, ...route.request().postDataJSON() } });
  });
  await page.goto('/app#settings');
  await page.getByLabel('Time zone', { exact: true }).fill('Asia/Tokyo');
  await page.getByRole('button', { name: 'Save display settings' }).click();
  try {
    await expect(page.getByLabel('Time zone', { exact: true })).toBeDisabled();
    await expect(page.getByLabel('Message style')).toBeDisabled();
    await expect(page.getByLabel('Mute all notifications')).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Use device time zone' })).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByRole('alert')).toContainText('Settings could not save.');
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('Asia/Tokyo');
  await expect(page.getByLabel('Time zone', { exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  expect(attempts).toBe(2);
});

test('preview ignores an old response when draft options change and renders provider text literally', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let attempts = 0;
  await page.route('**/v1/preferences/telegram-preview', async (route) => {
    if (++attempts === 1) {
      await gate;
      return route.fulfill({
        json: { text: 'Old detailed example', silent: false, time_zone: 'UTC' },
      });
    }
    return route.fulfill({
      json: {
        text: 'Example compact <b>literal text</b>',
        silent: false,
        time_zone: 'UTC',
        buttons: [{ text: '<img src=x onerror=alert(1)>', url: 'javascript:alert(1)' }],
      },
    });
  });
  await page.goto('/app#settings');
  await page.getByRole('button', { name: 'Preview message' }).click();
  try {
    await page.getByLabel('Message style').selectOption('compact');
  } finally {
    release();
  }
  await expect(page.getByRole('button', { name: 'Preview message' })).toBeEnabled();
  await expect(page.getByText('Old detailed example')).toHaveCount(0);
  await page.getByRole('button', { name: 'Preview message' }).click();
  await expect(page.locator('.telegram-preview pre')).toContainText('<b>literal text</b>');
  await expect(page.locator('.telegram-preview b')).toHaveCount(0);
  await expect(page.locator('.preview-actions')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.preview-actions img, .preview-actions a')).toHaveCount(0);
  expect(state.writes).toEqual([]);
});

test('personal settings remain accessible and usable on desktop and mobile', async ({ page }) => {
  await preferencesMock(page, { time_zone: 'America/Chicago' });
  await page.route('**/v1/preferences/telegram-preview', (route) =>
    route.fulfill({
      json: {
        text: 'Example alert — sample data\n\nNew observed low: USD 191.00\nDEN → DFW · 03/14/2027 · UA414\nTotal for 1 adult\nFare: Economy\nObserved 11/06/2026 1:30 AM America/Chicago (UTC-06:00)\nhttps://www.google.com/travel/flights',
        silent: false,
        time_zone: 'America/Chicago',
      },
    }),
  );
  for (const [name, viewport] of [
    ['desktop', { width: 1440, height: 1000 }],
    ['mobile', { width: 375, height: 812 }],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto('/app#settings');
    if (name === 'mobile') await page.reload();
    await page.getByRole('button', { name: 'Preview message' }).click();
    await expect(page.locator('.telegram-preview pre')).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    await expect(page.locator('[style]')).toHaveCount(0);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `artifacts/preferences-${name}.png`, fullPage: true });
    // Audit last: axe temporarily styles/focuses controls while measuring contrast.
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  }
});
