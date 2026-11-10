import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { flightUrl, mock, monitor, now, observation } from './fixtures';

test.use({ timezoneId: 'America/Chicago' });

const DAY = 86400;
const day = (seconds: number) =>
  new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'America/Chicago',
  }).format(seconds * 1000);

function watched(id: string, extra: Record<string, unknown> = {}) {
  return {
    ...structuredClone(monitor),
    id: id.repeat(32),
    stale: false,
    created_at: now - 6 * DAY,
    ...extra,
  };
}

async function flights(page: Page, items: () => unknown[]) {
  const reads = { count: 0 };
  await page.route(/\/v1\/monitors(?:\?|$)/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    reads.count += 1;
    const list = items();
    return route.fulfill({ json: { items: list, next_cursor: null, active_count: list.length } });
  });
  return reads;
}

test('a flight says how its price stands against the lowest recorded and when it was checked', async ({
  page,
}) => {
  await mock(page);
  await flights(page, () => [
    watched('a', { low_minor: observation.amount_minor }),
    watched('b', { low_minor: 19900 }),
    // Added an hour ago: its only price is trivially the lowest, so nothing is claimed.
    watched('c', { low_minor: observation.amount_minor, created_at: now - 3600 }),
    // An older service that does not report a low yet.
    watched('d', { created_at: undefined }),
  ]);
  await page.goto('/app');
  const cards = page.getByRole('article');
  await expect(cards).toHaveCount(4);
  const since = day(now - 6 * DAY);
  await expect(cards.nth(0).getByText(`Lowest since ${since}`, { exact: true })).toBeVisible();
  await expect(
    cards.nth(1).getByText(`Low since ${since}: $199.00`, { exact: true }),
  ).toBeVisible();
  await expect(cards.nth(2).getByText(/Low(est)? since/)).toHaveCount(0);
  await expect(cards.nth(3).getByText(/Low(est)? since/)).toHaveCount(0);

  // A glanceable age, with the exact moment one hover or one screen-reader phrase away.
  const checked = cards.nth(0).locator('.ticket-observation');
  await expect(checked).toContainText('Checked 30 minutes ago');
  await expect(checked).toHaveAttribute('title', /\d{1,2}:\d{2}/);
  await expect(checked.locator('.visually-hidden')).toContainText(/\d{1,2}:\d{2}/);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test('one failed check is retried quietly; a run of them, or a stop, is explained', async ({
  page,
}) => {
  await mock(page);
  const failed = (id: string, failures: number | undefined, extra = {}) =>
    watched(id, {
      last_error: 'provider_error',
      collection_failures: failures,
      collection_status: 'backoff',
      ...extra,
    });
  await flights(page, () => [
    // Retried within a couple of minutes: an old price still says it is waiting.
    failed('a', 1, { stale: true }),
    failed('b', 2),
    // Checks that have stopped are shown at once, however few failed.
    failed('c', 1, { last_error: 'provider_blocked', collection_status: 'blocked' }),
    // An older service that does not count failures.
    failed('d', undefined),
  ]);
  await page.goto('/app');
  const cards = page.getByRole('article');
  await expect(cards).toHaveCount(4);
  const note = (index: number) => cards.nth(index).locator('.collection-note');
  await expect(note(0)).toHaveCount(0);
  await expect(cards.nth(0).getByText('Waiting for an updated price')).toBeVisible();
  await expect(note(1)).toHaveText('The last check could not finish. We will keep trying.');
  await expect(cards.nth(1).getByText('Waiting for an updated price')).toHaveCount(0);
  await expect(note(2)).toHaveText(
    'The last check could not finish. Use Retry collection to try again.',
  );
  await expect(note(3)).toHaveText('The last check could not finish. We will keep trying.');
});

test('a first visit offers one thing to do and explains where a flight link comes from', async ({
  page,
}) => {
  const calls = await mock(page);
  const list: unknown[] = [];
  await flights(page, () => list);
  await page.goto('/app');
  const welcome = page.getByRole('region', { name: 'Which flight are you watching?' });
  await expect(welcome).toBeVisible();
  await expect(welcome.getByRole('listitem')).toHaveCount(3);
  await expect(page.getByRole('button', { name: 'Watch a flight', exact: true })).toHaveCount(0);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  await welcome.getByRole('button', { name: 'Watch your first flight', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const help = dialog.locator('details', { hasText: 'Where do I find the link?' });
  await expect(help).toHaveAttribute('open', '');
  await expect(help.getByRole('link', { name: /Google Flights/ })).toHaveAttribute(
    'href',
    'https://www.google.com/travel/flights',
  );

  const link = dialog.getByLabel('Google Flights link');
  const note = dialog.locator('.link-note');
  await expect(note).toHaveCount(0);
  await link.fill('google.com/travel/flights');
  await expect(note).toHaveText('Paste the whole link, starting with https://');
  await link.fill('https://example.com/travel/flights?tfs=abc');
  await expect(note).toHaveText(
    'That is not a Google Flights link. Copy it from google.com/travel/flights.',
  );
  await link.fill(`  ${flightUrl}  `);
  await expect(note).toHaveText('Google Flights link recognized.');
  // The help has done its job once a link is in hand.
  await expect(help).not.toHaveAttribute('open', '');
  expect(
    (
      await new AxeBuilder({ page })
        .include('dialog')
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  list.push(watched('b', { status: 'pending', latest: null, created_at: now }));
  await dialog.getByRole('button', { name: 'Start watching', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const created = calls.find((call) => call.path === '/v1/monitors' && call.method === 'POST');
  expect(created?.body.url).toBe(flightUrl);
});

test('someone with flights is not shown the link help unless they ask', async ({ page }) => {
  await mock(page);
  await page.goto('/app');
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  const help = page
    .getByRole('dialog')
    .locator('details', { hasText: 'Where do I find the link?' });
  await expect(help).not.toHaveAttribute('open', '');
  await help.locator('summary').click();
  await expect(help.getByText(/Copy the link from your browser/)).toBeVisible();
});

test('the first price of a new flight appears without pressing Refresh', async ({ page }) => {
  await mock(page);
  await page.clock.install();
  let priced = false;
  const reads = await flights(page, () => [
    priced
      ? watched('b', { created_at: now - 30, low_minor: 24500 })
      : watched('b', { status: 'pending', latest: null, created_at: now - 30 }),
  ]);
  await page.goto('/app');
  await expect(page.getByText('Awaiting first check', { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      'The first price usually arrives within a few minutes. This page updates by itself.',
    ),
  ).toBeVisible();
  const before = reads.count;

  await page.clock.runFor(11000);
  expect(reads.count).toBe(before);
  priced = true;
  await page.clock.runFor(1500);
  await expect(page.getByText('$245.00', { exact: true })).toBeVisible();
  await expect(page.getByText('Awaiting first check', { exact: true })).toHaveCount(0);
  expect(reads.count).toBe(before + 1);

  // With a price on the page the quick checks stop; the ordinary refresh takes over.
  await page.clock.runFor(30000);
  expect(reads.count).toBe(before + 1);
});

test('an old pending flight does not keep the page checking every few seconds', async ({
  page,
}) => {
  await mock(page);
  await page.clock.install();
  const reads = await flights(page, () => [
    watched('b', { status: 'pending', latest: null, created_at: now - 3600 }),
  ]);
  await page.goto('/app');
  await expect(page.getByText('Awaiting first check', { exact: true })).toBeVisible();
  const before = reads.count;
  await page.clock.runFor(40000);
  expect(reads.count).toBe(before);
});

test('flights keep their place while the first load is in flight', async ({ page }) => {
  await mock(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    await held;
    await route.fulfill({ json: { items: [monitor], active_count: 1 } });
  });
  await page.goto('/app');
  try {
    await expect(page.getByText('Loading your flights…', { exact: true })).toBeAttached();
    await expect(page.locator('.ticket-skeleton')).toHaveCount(2);
    // Not the empty-account invitation: nothing is known yet.
    await expect(page.getByRole('heading', { name: 'Which flight are you watching?' })).toHaveCount(
      0,
    );
  } finally {
    release();
  }
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.locator('.ticket-skeleton')).toHaveCount(0);
});
