import { expect, test } from '@playwright/test';
import { mock, monitor } from './fixtures';

const cursor = 'page/2+with=padding';
const followingCursor = 'page-3';
const second = { ...structuredClone(monitor), id: 'b'.repeat(32) };

test('an initial load failure shows a retry state instead of an empty account', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    if (++attempts === 1) {
      await route.fulfill({
        status: 503,
        json: { detail: 'Monitors are temporarily unavailable.' },
      });
    } else {
      await route.fulfill({ json: { items: [monitor], next_cursor: null, active_count: 1 } });
    }
  });
  await page.goto('/app');
  await expect(page.getByRole('alert')).toContainText('Monitors are temporarily unavailable.');
  await expect(page.getByRole('heading', { name: 'Your flights could not load' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Which flight are you watching?' })).toHaveCount(
    0,
  );
  await expect(page.getByRole('button', { name: 'Watch your first flight' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Watch a flight' })).toBeDisabled();
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByLabel('Monitor summary')).toContainText('1 of 3 monitors in use');
  await expect(page.getByRole('heading', { name: 'Your flights could not load' })).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(attempts).toBe(2);
});

test('a webhook load failure does not hide a successfully loaded empty monitor list', async ({
  page,
}) => {
  await mock(page);
  await page.route(/\/v1\/monitors(?:\?|$)/, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null, active_count: 0 } }),
  );
  await page.route(/\/v1\/webhooks(?:\?|$)/, (route) =>
    route.fulfill({ status: 503, json: { detail: 'Webhooks are temporarily unavailable.' } }),
  );
  await page.goto('/app');
  await expect(page.getByRole('alert')).toContainText('Webhooks are temporarily unavailable.');
  await expect(page.getByRole('heading', { name: 'Which flight are you watching?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Watch your first flight' })).toBeEnabled();
  // A first visit has one thing to do, offered once.
  await expect(page.getByRole('button', { name: 'Watch a flight', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Monitor summary')).not.toContainText('monitors in use');
  await expect(page.getByRole('heading', { name: 'Your flights could not load' })).toHaveCount(0);
});

test('monitor pagination keeps global quota, deduplicates rows and refreshes only loaded pages', async ({
  page,
}) => {
  await mock(page);
  const requested: (string | null)[] = [];
  const stopped = { ...structuredClone(monitor), status: 'cancelled' };
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    const position = new URL(route.request().url()).searchParams.get('cursor');
    requested.push(position);
    const body =
      position === cursor
        ? { items: [stopped, second], next_cursor: followingCursor, active_count: 3 }
        : { items: [stopped], next_cursor: cursor, active_count: 3 };
    await route.fulfill({ json: body });
  });
  await page.goto('/app');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByLabel('Monitor summary')).toContainText('3 of 3 monitors in use');
  await expect(page.getByRole('button', { name: 'Watch a flight' })).toBeDisabled();
  expect(requested).toEqual([null]);

  await page.getByRole('button', { name: 'Load more monitors' }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  expect(requested).toEqual([null, cursor]);

  const refreshedPage = page.waitForResponse(
    (response) => new URL(response.url()).searchParams.get('cursor') === cursor,
  );
  await page.getByRole('button', { name: 'Refresh dashboard' }).click();
  await refreshedPage;
  await expect(page.getByRole('button', { name: 'Refresh dashboard' })).toBeEnabled();
  await expect(page.getByRole('article')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Load more monitors' })).toBeVisible();
  expect(requested).toEqual([null, cursor, null, cursor]);
});

test('failed pagination keeps current monitors and permits retrying the same page', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    if (!new URL(route.request().url()).searchParams.has('cursor')) {
      await route.fulfill({ json: { items: [monitor], next_cursor: cursor, active_count: 2 } });
    } else if (++attempts === 1) {
      await route.fulfill({ status: 503, json: { detail: 'Earlier monitors could not load.' } });
    } else {
      await route.fulfill({ json: { items: [second], next_cursor: null, active_count: 2 } });
    }
  });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Load more monitors' }).click();
  await expect(page.getByRole('alert')).toContainText('Earlier monitors could not load.');
  await expect(page.getByRole('article')).toHaveCount(1);
  await page.getByRole('button', { name: 'Load more monitors' }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Load more monitors' })).toHaveCount(0);
  expect(attempts).toBe(2);
});

test('a refresh that fails on a later page preserves the previously loaded snapshot', async ({
  page,
}) => {
  await mock(page);
  let failRefresh = false;
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    const position = new URL(route.request().url()).searchParams.get('cursor');
    if (position && failRefresh) {
      await route.fulfill({ status: 503, json: { detail: 'Monitor refresh interrupted.' } });
    } else if (position) {
      await route.fulfill({ json: { items: [second], next_cursor: null, active_count: 2 } });
    } else {
      const first = failRefresh
        ? { ...monitor, latest: { ...monitor.latest, amount_minor: 12300 } }
        : monitor;
      await route.fulfill({ json: { items: [first], next_cursor: cursor, active_count: 2 } });
    }
  });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Load more monitors' }).click();
  await expect(page.getByRole('article')).toHaveCount(2);
  failRefresh = true;
  await page.getByRole('button', { name: 'Refresh dashboard' }).click();
  await expect(page.getByRole('alert')).toContainText('Monitor refresh interrupted.');
  await expect(page.getByRole('article')).toHaveCount(2);
  await expect(page.getByRole('article').first()).toContainText('$245.00');
  await expect(page.getByRole('article').first()).not.toContainText('$123.00');
});

test('refresh cancels an outstanding page so old results cannot reappear', async ({ page }) => {
  await mock(page);
  let refreshed = false;
  let releaseEarlier!: () => void;
  const waitForRelease = new Promise<void>((resolve) => {
    releaseEarlier = resolve;
  });
  let sawEarlier!: () => void;
  const earlierStarted = new Promise<void>((resolve) => {
    sawEarlier = resolve;
  });
  let earlierFinished!: () => void;
  const earlierSettled = new Promise<void>((resolve) => {
    earlierFinished = resolve;
  });
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    if (new URL(route.request().url()).searchParams.has('cursor')) {
      sawEarlier();
      await waitForRelease;
      try {
        await route.fulfill({ json: { items: [second], next_cursor: null, active_count: 2 } });
      } finally {
        earlierFinished();
      }
    } else {
      await route.fulfill({
        json: {
          items: [monitor],
          next_cursor: refreshed ? null : cursor,
          active_count: refreshed ? 1 : 2,
        },
      });
    }
  });
  await page.goto('/app');
  const cancelled = page.waitForEvent('requestfailed', {
    predicate: (request) => new URL(request.url()).searchParams.get('cursor') === cursor,
  });
  await page.getByRole('button', { name: 'Load more monitors' }).click();
  try {
    await earlierStarted;
    refreshed = true;
    await page.getByRole('button', { name: 'Refresh dashboard' }).click();
    await cancelled;
    await expect(page.getByRole('button', { name: 'Refresh dashboard' })).toBeEnabled();
  } finally {
    releaseEarlier();
  }
  await earlierSettled;
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByLabel('Monitor summary')).toContainText('1 of 3 monitors in use');
  await expect(page.getByRole('button', { name: 'Load more monitors' })).toHaveCount(0);
  await expect(page.getByRole('alert')).toHaveCount(0);
});
