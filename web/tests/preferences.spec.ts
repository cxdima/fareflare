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
  telegram_templates: {},
  telegram_show_flight_numbers: true,
  telegram_show_observed_time: true,
  telegram_show_fare: true,
  telegram_show_buttons: true,
  telegram_silent: false,
  diagnostics: false,
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

type SettingsSection = 'Display' | 'Notifications' | 'Connections' | 'Security';

function sectionButton(page: Page, name: SettingsSection) {
  return page
    .getByRole('navigation', { name: 'Settings sections' })
    .getByRole('button', { name, exact: true });
}

async function showSection(page: Page, name: SettingsSection) {
  const button = sectionButton(page, name);
  await button.click();
  await expect(button).toHaveAttribute('aria-pressed', 'true');
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
  await showSection(page, 'Notifications');
  await page.getByLabel('Message style').selectOption('compact');
  await page.getByLabel('Flight numbers', { exact: true }).uncheck();
  await page.getByLabel('Fare name', { exact: true }).uncheck();
  await page.getByLabel('Send silently', { exact: true }).check();
  await page.getByRole('button', { name: 'Preview message' }).click();
  const preview = page.locator('.telegram-preview pre');
  await expect(preview).toContainText('Example alert');
  await expect(preview).toContainText('USD 191,00');
  await expect(preview).toContainText('Asia/Tokyo (UTC+09:00)');
  await expect(preview).not.toContainText('UA 414');
  await expect(preview).not.toContainText('Fare:');
  const exampleButtons = page.getByRole('group', { name: 'Example Telegram buttons' });
  await expect(exampleButtons).toContainText('View flight');
  await expect(exampleButtons).toContainText('Open Fareflare');
  await expect(exampleButtons.getByRole('link')).toHaveCount(0);
  saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved.telegram_style).toBe('detailed');
  expect(saved.telegram_silent).toBe(false);
  // The classic style and the flight list are rendered by the real service too.
  await page.getByLabel('Message style').selectOption('classic');
  await page.getByRole('button', { name: 'Preview message' }).click();
  await expect(preview).toContainText('New low!');
  await expect(preview).toContainText('191 $ (was 199 $, −8 $ · −4%)');
  await expect(exampleButtons).not.toContainText('View flight');
  await page.getByLabel('Show an example of').selectOption('flight_list');
  await page.getByRole('button', { name: 'Preview message' }).click();
  await expect(preview).toContainText('Example flight list');
  await expect(preview).toContainText('🔥 at the low');
  await page.getByLabel('Message style').selectOption('compact');
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
  await showSection(page, 'Security');
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
    await expect(page.getByRole('button', { name: 'Use device time zone' })).toBeDisabled();
    await showSection(page, 'Notifications');
    await expect(page.getByLabel('Message style')).toBeDisabled();
    await expect(page.getByLabel('Mute all notifications')).toBeDisabled();
    await showSection(page, 'Display');
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
  await page.route('**/v1/preferences/telegram-preview*', async (route) => {
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
  await showSection(page, 'Notifications');
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

test('settings sections work with the keyboard and retain unsaved drafts until saved', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  await page.goto('/app#settings');
  await expect(sectionButton(page, 'Display')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('Message style')).toBeHidden();
  await page.getByLabel('Time zone', { exact: true }).fill('Asia/Tokyo');
  await page.getByLabel('Regional format', { exact: true }).selectOption('de-DE');

  await sectionButton(page, 'Notifications').focus();
  await page.keyboard.press('Enter');
  await expect(sectionButton(page, 'Notifications')).toHaveAttribute('aria-pressed', 'true');
  await expect(sectionButton(page, 'Display')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByLabel('Time zone', { exact: true })).toBeHidden();
  await page.getByLabel('Message style').selectOption('compact');
  await page.getByLabel('Send silently', { exact: true }).check();
  await page.getByLabel('Mute all notifications').check();
  await page.getByLabel('Muted routes').fill('DEN-DFW');

  await sectionButton(page, 'Connections').focus();
  await page.keyboard.press('Space');
  await expect(sectionButton(page, 'Connections')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: 'Connected applications' })).toBeVisible();
  await expect(page.getByLabel('Message style')).toBeHidden();
  await showSection(page, 'Security');
  await expect(page.getByRole('button', { name: 'Delete my account' })).toBeVisible();

  await showSection(page, 'Display');
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('Asia/Tokyo');
  await expect(page.getByLabel('Regional format', { exact: true })).toHaveValue('de-DE');
  expect(state.writes).toEqual([]);
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  await showSection(page, 'Notifications');
  await expect(page.getByLabel('Message style')).toHaveValue('compact');
  await expect(page.getByLabel('Send silently', { exact: true })).toBeChecked();
  await expect(page.getByLabel('Mute all notifications')).toBeChecked();
  await expect(page.getByLabel('Muted routes')).toHaveValue('DEN-DFW');
  expect(state.value()).toMatchObject({
    time_zone: 'Asia/Tokyo',
    locale: 'de-DE',
    telegram_style: 'detailed',
    telegram_silent: false,
    muted: false,
    muted_routes: [],
  });
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  await expect(page.getByLabel('Mute all notifications')).toBeChecked();
  await expect(page.getByLabel('Muted routes')).toHaveValue('DEN-DFW');
  expect(state.value()).toMatchObject({ telegram_style: 'compact', telegram_silent: true });
  expect(state.value().muted).toBe(false);
  expect(state.writes).toHaveLength(2);
});

test('personal settings remain accessible and usable on desktop and mobile', async ({ page }) => {
  await preferencesMock(page, { time_zone: 'America/Chicago' });
  await page.route('**/v1/preferences/telegram-preview*', (route) =>
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
    for (const section of ['Display', 'Notifications', 'Connections', 'Security'] as const) {
      await showSection(page, section);
      if (section === 'Display') {
        await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('America/Chicago');
      } else if (section === 'Notifications') {
        await page.getByRole('button', { name: 'Preview message' }).click();
        await expect(page.locator('.telegram-preview pre')).toBeVisible();
      } else if (section === 'Connections') {
        await expect(
          page.getByRole('button', { name: 'Revoke access for Travel helper', exact: true }),
        ).toBeVisible();
      } else {
        await expect(page.getByRole('button', { name: 'Delete my account' })).toBeVisible();
      }
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      ).toBeTruthy();
      await expect(page.locator('[style]')).toHaveCount(0);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: `artifacts/preferences-${name}-${section.toLowerCase()}.png`,
        fullPage: true,
      });
      // Audit last: axe temporarily styles/focuses controls while measuring contrast.
      expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
      // Start the next audit from a clean document without axe's temporary measurements.
      await page.reload();
    }
  }
});

const catalog = {
  templates: [
    { key: 'tracking_started', label: 'Tracking started', optional: false },
    { key: 'new_low', label: 'New low', optional: false },
    { key: 'below_price', label: 'Target reached', optional: false },
    { key: 'rebound', label: 'Price rebound', optional: false },
    { key: 'flight_group', label: 'Flight list heading', optional: true },
    { key: 'flight_row', label: 'Flight list row', optional: false },
  ],
  placeholders: Object.fromEntries(
    ['tracking_started', 'new_low', 'below_price', 'rebound', 'flight_group', 'flight_row'].map(
      (key) => [
        key,
        [
          { name: 'route', description: 'Airports', example: 'DFW → DEN' },
          { name: 'price_short', description: 'Price with a symbol', example: '$246' },
        ],
      ],
    ),
  ),
  presets: Object.fromEntries(
    ['detailed', 'compact', 'classic'].map((style) => [
      style,
      {
        tracking_started: `${style} started {route}`,
        new_low: `${style} low {route}`,
        below_price: `${style} target {route}`,
        rebound: `${style} rebound {route}`,
        flight_group: style === 'classic' ? '🛫 {route}' : '',
        flight_row: `${style} row {route}`,
      },
    ]),
  ),
  limits: { characters: 800, lines: 20, placeholders: 40 },
};

test('custom wording starts from a style, inserts details and previews before saving', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  await page.route('**/v1/preferences/telegram-templates', (route) =>
    route.fulfill({ json: catalog }),
  );
  const previews: { message: string | null; body: Partial<Preferences> }[] = [];
  await page.route('**/v1/preferences/telegram-preview*', (route) => {
    const request = route.request();
    previews.push({
      message: new URL(request.url()).searchParams.get('message'),
      body: request.postDataJSON(),
    });
    return route.fulfill({
      json: { text: 'Example flight list — sample data', silent: false, time_zone: 'UTC' },
    });
  });
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await page.getByLabel('Message style').selectOption('classic');
  await expect(page.getByLabel('Message to edit')).toHaveCount(0);
  await page.getByLabel('Message style').selectOption('custom');
  // A first draft continues from the style that was selected before it.
  const newLow = page.getByLabel('New low message', { exact: true });
  await expect(newLow).toHaveValue('classic low {route}');
  await expect(page.getByLabel('Flight numbers', { exact: true })).toBeDisabled();
  await expect(page.getByLabel('Buttons under alerts', { exact: true })).toBeEnabled();

  await page.getByLabel('Start from a style').selectOption('compact');
  await page.getByRole('button', { name: 'Copy wording' }).click();
  await expect(newLow).toHaveValue('compact low {route}');

  await page.getByLabel('Message to edit').selectOption('flight_row');
  await expect(newLow).toBeHidden();
  const row = page.getByLabel('Flight list row message', { exact: true });
  await row.fill('Now ');
  await page
    .getByRole('group', { name: 'Details you can add to the Flight list row message' })
    .getByRole('button', { name: '{price_short}', exact: true })
    .click();
  await expect(row).toHaveValue('Now {price_short}');
  await expect(row).toBeFocused();
  await expect(page.locator('#template-help-flight_row')).toContainText('17 of 800 characters.');
  // Editing a list template previews the list it belongs to.
  await expect(page.getByLabel('Show an example of')).toHaveValue('flight_list');
  await page.getByRole('button', { name: 'Preview message' }).click();
  await expect(page.locator('.telegram-preview pre')).toContainText('Example flight list');
  expect(previews).toHaveLength(1);
  expect(previews[0].message).toBe('flight_list');
  expect(previews[0].body.telegram_templates).toMatchObject({
    new_low: 'compact low {route}',
    flight_row: 'Now {price_short}',
    flight_group: '',
  });
  expect(state.writes).toEqual([]);

  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page.locator('[style]')).toHaveCount(0);
  await page.screenshot({ path: 'artifacts/preferences-custom-wording.png', fullPage: true });

  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]).toMatchObject({
    telegram_style: 'custom',
    telegram_templates: { flight_row: 'Now {price_short}', rebound: 'compact rebound {route}' },
  });
  // Returning later shows the saved wording, not a fresh preset.
  await page.reload();
  await showSection(page, 'Notifications');
  await page.getByLabel('Message to edit').selectOption('flight_row');
  await expect(page.getByLabel('Flight list row message', { exact: true })).toHaveValue(
    'Now {price_short}',
  );
});

test('a template mistake is explained in plain words and the draft is kept', async ({ page }) => {
  await mock(page);
  await page.route('**/v1/preferences/telegram-templates', (route) =>
    route.fulfill({ json: catalog }),
  );
  await page.route('**/v1/preferences', (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({
          status: 422,
          json: {
            detail: [
              {
                loc: ['body', 'telegram_templates'],
                msg: 'Value error, New low: Unknown placeholder {nope}',
                type: 'value_error',
              },
            ],
          },
        })
      : route.fulfill({ json: defaults }),
  );
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await page.getByLabel('Message style').selectOption('custom');
  const newLow = page.getByLabel('New low message', { exact: true });
  await newLow.fill('{nope}');
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByRole('alert')).toHaveText('New low: Unknown placeholder {nope}');
  await expect(newLow).toHaveValue('{nope}');
});

test('technical details stay hidden until the account opts in', async ({ page }) => {
  const state = await preferencesMock(page);
  const failing = {
    ...monitor,
    last_error: 'timeout',
    collection_failures: 6,
    latest: observation,
  };
  await page.route('**/v1/monitors*', (route) =>
    route.fulfill({ json: { items: [failing], next_cursor: null, active_count: 1 } }),
  );
  await page.goto('/app#monitors');
  const note = page.locator('.collection-note');
  await expect(note).toContainText('The last check could not finish.');
  await expect(note).not.toContainText('timeout');
  await expect(page.getByText('Diagnostic code')).toHaveCount(0);

  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await showSection(page, 'Notifications');
  const toggle = page.getByLabel('Show failure codes and send diagnostic notices');
  await expect(toggle).not.toBeChecked();
  await toggle.check();
  await page.getByRole('button', { name: 'Save technical settings' }).click();
  await expect(page.getByText('Technical settings saved.')).toBeVisible();
  expect(state.writes).toEqual([{ diagnostics: true }]);

  await page.getByRole('link', { name: 'Flight monitors', exact: true }).click();
  await expect(note).toContainText('Diagnostic code: timeout · failed checks in a row: 6');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
