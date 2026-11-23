import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { messagePreview, mock, monitor, observation, templateCatalog } from './fixtures';
import type { Preferences } from '../src/app/core/types';

test.use({ timezoneId: 'America/Chicago' });

const defaults: Preferences = {
  muted: false,
  muted_routes: [],
  time_zone: null,
  locale: 'en-US',
  hour_cycle: 'auto',
  telegram_style: 'compact',
  telegram_templates: {},
  telegram_show_flight_numbers: true,
  telegram_show_times: true,
  telegram_show_observed_time: true,
  telegram_show_fare: true,
  telegram_show_buttons: true,
  telegram_list_order: 'departure',
  telegram_silent: false,
  quiet_hours: null,
  diagnostics: false,
};
/** The sample trip leaves sixteen weeks after the preview is made, so its day is not fixed. */
const day = '[A-Z][a-z]{2} \\d{1,2}';

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

/** One option of the message style switch. */
function styleButton(page: Page, name: 'Compact' | 'Detailed' | 'Custom') {
  return page
    .getByRole('group', { name: 'Message style' })
    .getByRole('button', { name, exact: true });
}

/** The message inside the preview's chat bubble. */
function previewText(page: Page) {
  return page.locator('.telegram-preview .bubble-text');
}

/** One option of the flight list order switch. */
function orderButton(page: Page, name: 'By departure' | 'By price') {
  return page
    .getByRole('group', { name: 'Flight list order' })
    .getByRole('button', { name, exact: true });
}

test('actual account preferences persist and preview does not save or send', async ({
  page,
}, info) => {
  await page.goto('/register');
  const password = 'private-preferences-test-password';
  await page
    .getByLabel('Email', { exact: true })
    .fill(`preferencesuser${info.retry}-${Date.now()}@example.com`);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL('/app');
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
  // The preview appears by itself, in the saved region and clock, and follows every change.
  await expect(styleButton(page, 'Compact')).toHaveAttribute('aria-pressed', 'true');
  const preview = previewText(page);
  await expect(preview.locator('.bubble-line')).toHaveText([
    '🔥 New low · 191 $ (was 199 $)',
    new RegExp(`^DEN → DFW · ${day} · UA 414$`),
    '15:50 → 18:54',
  ]);
  await expect(preview.locator('.run-bold')).toHaveText(['New low', '191 $']);
  await expect(preview).not.toContainText('USD');
  await page.getByLabel('Flight numbers', { exact: true }).uncheck();
  await expect(preview).not.toContainText('UA 414');
  // Each style offers only the details it shows.
  await expect(page.getByLabel('Fare name', { exact: true })).toHaveCount(0);
  await styleButton(page, 'Detailed').click();
  await expect(preview).toContainText('191 $ (was 199 $, −8 $ · −4%)');
  await expect(preview).toContainText('United · Economy · Total for 1 adult');
  await expect(preview).toContainText('Checked');
  await page.getByLabel('Fare name', { exact: true }).uncheck();
  await expect(preview).not.toContainText('Economy');
  await page.getByLabel('Send silently', { exact: true }).check();
  await expect(page.locator('.bubble-meta')).toContainText('Silent');
  const exampleButtons = page.getByRole('group', { name: 'Example Telegram buttons' });
  await expect(exampleButtons).toContainText('View flight');
  await expect(exampleButtons).toContainText('Open Fareflare');
  await expect(exampleButtons.getByRole('link')).toHaveCount(0);
  saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved.telegram_style).toBe('compact');
  expect(saved.telegram_silent).toBe(false);
  expect(saved.telegram_show_flight_numbers).toBe(true);
  // Other situations show what the wording does when details are added or missing.
  await styleButton(page, 'Compact').click();
  const sample = page.getByLabel('Sample', { exact: true });
  await sample.selectOption('round_trip');
  await expect(preview.locator('.bubble-line')).toHaveText([
    '🔥 New low · 382 $ for 2 adults (was 398 $)',
    new RegExp(`^DEN ⇄ DFW · ${day} – ${day}$`),
    '15:50 → 18:54',
    '↩ 17:09 → 18:14',
  ]);
  await sample.selectOption('untimed');
  await expect(preview.locator('.bubble-line')).toHaveCount(2);
  await sample.selectOption('late');
  await expect(preview.locator('.bubble-line').last()).toContainText('Checked');
  await sample.selectOption('one_way');
  // The flight list is rendered by the real service too, and has no buttons.
  await page.getByLabel('Message', { exact: true }).selectOption('flight_list');
  await expect(preview.locator('.bubble-line').first()).toHaveText(
    new RegExp(`^🛫 DEN → DFW · ${day}$`),
  );
  await expect(preview).toContainText('🔥 at the low');
  await expect(preview.locator('.bubble-line').nth(1)).toContainText('214 $');
  await expect(preview.locator('.run-code').first()).toHaveText('UA 1565');
  await expect(exampleButtons).toHaveCount(0);
  // Ordering by price moves the cheapest flight to the top of its day.
  await page.getByLabel('Message', { exact: true }).selectOption('new_low');
  await orderButton(page, 'By price').click();
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('flight_list');
  await expect(preview.locator('.bubble-line').nth(1)).toContainText('191 $ 🔥 at the low');
  await expect(page.locator('#list-order-help')).toContainText('lowest price');
  saved = await (await page.request.get('/v1/preferences')).json();
  expect(saved.telegram_list_order).toBe('departure');
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
    telegram_list_order: 'price',
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

test('flight cards show departure and arrival times in the account clock style', async ({
  page,
}) => {
  const state = await preferencesMock(page, { hour_cycle: 'h23' });
  const outbound = {
    departs: '15:50',
    arrives: '00:54',
    arrival_day_offset: 1,
    duration_minutes: 124,
  };
  const back = { departs: '09:05', arrives: '12:14', arrival_day_offset: 0, duration_minutes: 129 };
  const returning = {
    date: '2027-03-21',
    legs: [
      { origin: 'DFW', destination: 'DEN', airline: 'UA', number: '2049', date: '2027-03-21' },
    ],
  };
  let items: unknown[] = [{ ...monitor, latest: { ...observation, schedule: [outbound] } }];
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({ json: { items, active_count: 1 } }),
  );
  await page.goto('/app');
  const times = page.locator('.ticket-times');
  await expect(times).toHaveCount(1);
  await expect(times.locator('[aria-hidden="true"]')).toHaveText('15:50 → 00:54 +1 · 2 hr 4 min');
  await expect(times.locator('.visually-hidden')).toHaveText(
    'Departs 15:50, arrives 00:54, 1 day later, 2 hr 4 min',
  );

  // A round trip lists each direction, in a 12-hour clock when the account prefers one.
  items = [
    {
      ...monitor,
      target: { ...monitor.target, segments: [...monitor.target.segments, returning] },
      latest: { ...observation, schedule: [outbound, back] },
    },
  ];
  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await page.getByLabel('Clock', { exact: true }).selectOption('h12');
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  await page.reload();
  await page.getByRole('link', { name: 'Flight monitors', exact: true }).click();
  await expect(times).toHaveCount(2);
  await expect(times.nth(1).locator('[aria-hidden="true"]')).toHaveText(
    /↩ 9:05\sAM → 12:14\sPM · 2 hr 9 min/,
  );
  await expect(times.nth(1).locator('.visually-hidden')).toHaveText(/^Return departs 9:05\sAM/);

  // Times recorded for a different shape of trip, or malformed ones, are never shown.
  for (const schedule of [[outbound], [{ departs: '25:00', arrives: '12:14' }, back], 'soon']) {
    items = [{ ...(items[0] as object), latest: { ...observation, schedule } }];
    await page.reload();
    await expect(page.locator('.ticket-date')).toBeVisible();
    await expect(times).toHaveCount(0);
  }

  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await showSection(page, 'Notifications');
  await page.getByLabel('Departure and arrival times', { exact: true }).uncheck();
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  expect(state.writes.at(-1)).toMatchObject({ telegram_show_times: false });
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
    await expect(styleButton(page, 'Detailed')).toBeDisabled();
    await expect(page.getByLabel('Send silently', { exact: true })).toBeDisabled();
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

test('preview follows the draft, ignores an out-of-date answer and renders provider text literally', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const requests: Partial<Preferences>[] = [];
  const literal = '<b>literal text</b>';
  await page.route('**/v1/preferences/telegram-preview*', async (route) => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      await gate;
      // The page has stopped waiting for this answer, so sending it may fail.
      return route
        .fulfill({
          json: { ...messagePreview, lines: [[{ ...messagePreview.lines[1][0], text: 'Old' }]] },
        })
        .catch(() => undefined);
    }
    return route.fulfill({
      json: {
        ...messagePreview,
        lines: [[{ ...messagePreview.lines[1][0], text: literal, bold: true }]],
        buttons: [{ text: '<img src=x onerror=alert(1)>', url: 'javascript:alert(1)' }],
      },
    });
  });
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  // Nothing needs to be pressed: opening the section asks for the preview.
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toMatchObject({ telegram_style: 'compact', quiet_hours: null });
  try {
    await styleButton(page, 'Detailed').click();
    await expect(previewText(page)).toHaveText(literal);
  } finally {
    release();
  }
  expect(requests[1]).toMatchObject({ telegram_style: 'detailed' });
  await expect(page.getByText('Old', { exact: true })).toHaveCount(0);
  await expect(previewText(page).locator('.run-bold')).toHaveText(literal);
  await expect(page.locator('.telegram-preview b')).toHaveCount(0);
  await expect(page.locator('.preview-actions')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.preview-actions img, .preview-actions a')).toHaveCount(0);
  // Several quick changes are answered once, with the last of them.
  const before = requests.length;
  for (const label of ['Flight numbers', 'Fare name', 'Send silently']) {
    await page.getByLabel(label, { exact: true }).click();
  }
  await expect.poll(() => requests.length).toBe(before + 1);
  expect(requests.at(-1)).toMatchObject({
    telegram_show_flight_numbers: false,
    telegram_show_fare: false,
    telegram_silent: true,
  });
  expect(state.writes).toEqual([]);
});

test('a preview that cannot be made says why and keeps the last one', async ({ page }) => {
  await preferencesMock(page);
  let broken = false;
  await page.route('**/v1/preferences/telegram-preview*', (route) =>
    broken
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
      : route.fulfill({ json: messagePreview }),
  );
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await expect(previewText(page)).toContainText('New low · $191');
  await styleButton(page, 'Custom').click();
  broken = true;
  await page.getByLabel('New low message', { exact: true }).fill('{nope}');
  const problem = page.locator('.telegram-preview').getByRole('alert');
  await expect(problem).toHaveText('New low: Unknown placeholder {nope}');
  await expect(previewText(page)).toContainText('New low · $191');
  // Fixing the wording clears the message.
  broken = false;
  await page.getByLabel('New low message', { exact: true }).fill('{price_short}');
  await expect(problem).toHaveCount(0);
});

test('message styles that cannot load offer a retry and leave other settings usable', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  let attempts = 0;
  await page.route('**/v1/preferences/telegram-templates', (route) =>
    ++attempts === 1
      ? route.fulfill({ status: 503, json: { detail: 'Message styles are unavailable.' } })
      : route.fulfill({ json: templateCatalog }),
  );
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await expect(page.getByRole('alert')).toContainText('Message styles are unavailable.');
  // Muting does not depend on message styles.
  await page.getByLabel('Mute all notifications').check();
  await page.getByRole('button', { name: 'Save preferences', exact: true }).click();
  await expect(page.getByText('Notification preferences saved.')).toBeVisible();
  expect(state.writes).toEqual([{ muted: true, muted_routes: [] }]);
  await page.getByRole('button', { name: 'Retry message styles' }).click();
  await expect(styleButton(page, 'Compact')).toHaveAttribute('aria-pressed', 'true');
  await expect(previewText(page)).toBeVisible();
});

test('settings sections work with the keyboard and retain unsaved drafts until saved', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  await page.goto('/app#settings');
  await expect(sectionButton(page, 'Display')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('group', { name: 'Message style' })).toBeHidden();
  await page.getByLabel('Time zone', { exact: true }).fill('Asia/Tokyo');
  await page.getByLabel('Regional format', { exact: true }).selectOption('de-DE');

  await sectionButton(page, 'Notifications').focus();
  await page.keyboard.press('Enter');
  await expect(sectionButton(page, 'Notifications')).toHaveAttribute('aria-pressed', 'true');
  await expect(sectionButton(page, 'Display')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByLabel('Time zone', { exact: true })).toBeHidden();
  // The style switch is a group of buttons, each reachable and operable from the keyboard.
  await styleButton(page, 'Detailed').focus();
  await page.keyboard.press('Enter');
  await expect(styleButton(page, 'Detailed')).toHaveAttribute('aria-pressed', 'true');
  await expect(styleButton(page, 'Compact')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#telegram-style-help')).toHaveText(
    'Adds the airline, flight length, fare and time of the check.',
  );
  await page.getByLabel('Send silently', { exact: true }).check();
  await page.getByLabel('Mute all notifications').check();
  await page.getByLabel('Muted routes').fill('DEN-DFW');

  await sectionButton(page, 'Connections').focus();
  await page.keyboard.press('Space');
  await expect(sectionButton(page, 'Connections')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: 'Connected applications' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Message style' })).toBeHidden();
  await showSection(page, 'Security');
  await expect(page.getByRole('button', { name: 'Delete my account' })).toBeVisible();

  await showSection(page, 'Display');
  await expect(page.getByLabel('Time zone', { exact: true })).toHaveValue('Asia/Tokyo');
  await expect(page.getByLabel('Regional format', { exact: true })).toHaveValue('de-DE');
  expect(state.writes).toEqual([]);
  await page.getByRole('button', { name: 'Save display settings' }).click();
  await expect(page.getByText('Display settings saved.')).toBeVisible();
  await showSection(page, 'Notifications');
  await expect(styleButton(page, 'Detailed')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('Send silently', { exact: true })).toBeChecked();
  await expect(page.getByLabel('Mute all notifications')).toBeChecked();
  await expect(page.getByLabel('Muted routes')).toHaveValue('DEN-DFW');
  expect(state.value()).toMatchObject({
    time_zone: 'Asia/Tokyo',
    locale: 'de-DE',
    telegram_style: 'compact',
    telegram_silent: false,
    muted: false,
    muted_routes: [],
  });
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  await expect(page.getByLabel('Mute all notifications')).toBeChecked();
  await expect(page.getByLabel('Muted routes')).toHaveValue('DEN-DFW');
  expect(state.value()).toMatchObject({ telegram_style: 'detailed', telegram_silent: true });
  expect(state.value().muted).toBe(false);
  expect(state.writes).toHaveLength(2);
});

test('personal settings remain accessible and usable on desktop and mobile', async ({ page }) => {
  await preferencesMock(page, { time_zone: 'America/Chicago' });
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
        await expect(previewText(page)).toContainText('New low · $191 (was $199)');
        // On a narrow screen the preview sits directly under the style it illustrates.
        const [style, preview, switches] = await Promise.all(
          ['.style-field', '.telegram-preview', '.telegram-settings'].map(async (selector) => {
            const box = await page.locator(selector).boundingBox();
            return box!;
          }),
        );
        if (name === 'mobile') {
          expect(preview.y).toBeGreaterThan(style.y + style.height - 1);
          expect(switches.y).toBeGreaterThan(preview.y + preview.height - 1);
        } else {
          expect(preview.x).toBeGreaterThan(style.x + style.width - 1);
          expect(Math.abs(preview.y - style.y)).toBeLessThan(2);
        }
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

test('custom wording starts from a style, inserts details and previews before saving', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  const previews: {
    message: string | null;
    sample: string | null;
    body: Partial<Preferences>;
  }[] = [];
  // The service remarks on wording that leaves out what a reader needs; it never refuses it.
  const hints = ['A flight in the list does not show which flight it is about.'];
  await page.route('**/v1/preferences/telegram-preview*', (route) => {
    const request = route.request();
    const asked = new URL(request.url()).searchParams;
    const body: Partial<Preferences> = request.postDataJSON();
    previews.push({ message: asked.get('message'), sample: asked.get('sample'), body });
    const bare = body.telegram_templates?.flight_row === 'Now {price_short}';
    return route.fulfill({ json: { ...messagePreview, hints: bare ? hints : [] } });
  });
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await styleButton(page, 'Detailed').click();
  await expect(page.getByLabel('Message to edit')).toHaveCount(0);
  await expect(page.getByLabel('Fare name', { exact: true })).toBeVisible();
  await styleButton(page, 'Custom').click();
  // A first draft continues from the style that was selected before it.
  const newLow = page.getByLabel('New low message', { exact: true });
  await expect(newLow).toHaveValue('detailed low {route}');
  // A custom message says exactly what its wording says, so there is nothing to switch off.
  await expect(page.getByRole('group', { name: 'Include in alerts' })).toHaveCount(0);
  await expect(page.getByLabel('Flight numbers', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Buttons under alerts', { exact: true })).toBeEnabled();

  // A message returns to a built-in wording by itself; the others keep theirs.
  const reset = page.getByRole('group', { name: 'Reset this message to' });
  await reset.getByRole('button', { name: 'Compact', exact: true }).click();
  await expect(newLow).toHaveValue('compact low {route}');

  await page.getByLabel('Message to edit').selectOption('flight_row');
  await expect(newLow).toBeHidden();
  const row = page.getByLabel('Flight list row message', { exact: true });
  await row.fill('Now ');
  // Details are listed under headings, each with an example of what it shows.
  const details = page.getByRole('group', {
    name: 'Details you can add to the Flight list row message',
  });
  await expect(details.locator('.placeholder-group-name')).toHaveText(['Price', 'Trip']);
  // The name a screen reader announces is the text on the button; its title explains it.
  const price = details.getByRole('button', { name: '{price_short} $246', exact: true });
  await expect(price).toHaveAttribute('title', 'Price with a symbol');
  await price.click();
  await expect(row).toHaveValue('Now {price_short}');
  await expect(row).toBeFocused();
  await expect(page.locator('#template-help-flight_row')).toContainText('17 of 800 characters.');
  // Editing a list template previews the list it belongs to, with the draft as it stands.
  await expect(page.getByLabel('Message', { exact: true })).toHaveValue('flight_list');
  await expect
    .poll(() => previews.at(-1))
    .toMatchObject({
      message: 'flight_list',
      sample: 'one_way',
      body: {
        telegram_style: 'custom',
        telegram_templates: {
          new_low: 'compact low {route}',
          rebound: 'detailed rebound {route}',
          flight_row: 'Now {price_short}',
          flight_group: '',
        },
      },
    });
  // The remark sits under the preview as a note; saving stays possible.
  const remarks = page.locator('.telegram-preview').getByRole('status');
  await expect(remarks).toHaveText(hints[0]);
  await expect(page.locator('.telegram-preview').getByRole('alert')).toHaveCount(0);
  expect(state.writes).toEqual([]);

  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page.locator('[style]')).toHaveCount(0);
  await page.screenshot({ path: 'artifacts/preferences-custom-wording.png', fullPage: true });

  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0]).toMatchObject({
    telegram_style: 'custom',
    telegram_templates: { flight_row: 'Now {price_short}', rebound: 'detailed rebound {route}' },
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
  await styleButton(page, 'Custom').click();
  const newLow = page.getByLabel('New low message', { exact: true });
  await newLow.fill('{nope}');
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByRole('alert')).toHaveText('New low: Unknown placeholder {nope}');
  await expect(newLow).toHaveValue('{nope}');
});

test('quiet hours are a window that is checked before saving and kept when switched off', async ({
  page,
}) => {
  const state = await preferencesMock(page);
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  const toggle = page.getByLabel('Quiet hours', { exact: true });
  await expect(toggle).not.toBeChecked();
  await expect(page.getByLabel('From', { exact: true })).toBeHidden();
  await toggle.check();
  const from = page.getByLabel('From', { exact: true });
  const until = page.getByLabel('Until', { exact: true });
  await expect(from).toHaveValue('22:00');
  await expect(until).toHaveValue('07:00');

  // A window that starts and ends at the same time says nothing, so it is not sent.
  await until.fill('22:00');
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.locator('#quiet-hours-error')).toHaveText('Choose two different times.');
  expect(state.writes).toEqual([]);

  await from.fill('23:30');
  await until.fill('06:15');
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  expect(state.writes[0]).toMatchObject({ quiet_hours: '23:30-06:15' });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await toggle.uncheck();
  await page.getByRole('button', { name: 'Save Telegram settings' }).click();
  await expect(page.getByText('Telegram message settings saved.')).toBeVisible();
  expect(state.writes[1]).toMatchObject({ quiet_hours: null });
  // Switching it back on offers the window that was used before.
  await toggle.check();
  await expect(page.getByLabel('From', { exact: true })).toHaveValue('23:30');
});

test('a saved quiet-hours window is shown when settings open', async ({ page }) => {
  await preferencesMock(page, { quiet_hours: '21:00-08:00' });
  await page.goto('/app#settings');
  await showSection(page, 'Notifications');
  await expect(page.getByLabel('Quiet hours', { exact: true })).toBeChecked();
  await expect(page.getByLabel('From', { exact: true })).toHaveValue('21:00');
  await expect(page.getByLabel('Until', { exact: true })).toHaveValue('08:00');
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
