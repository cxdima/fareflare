import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { mock, monitor, observation, now } from './fixtures';

const recent = { ...observation, observed_at: now - 900 };
const earlier = { ...observation, amount_minor: 30000, observed_at: now - 1800 };
const old = { ...observation, amount_minor: 11000, observed_at: now - 8 * 86400 };

test('history ranges, pagination and CSV all describe the same loaded prices', async ({ page }) => {
  await mock(page);
  const cursor = 'older/with+padding=';
  const requested: (string | null)[] = [];
  await page.route('**/history**', async (route) => {
    const value = new URL(route.request().url()).searchParams.get('cursor');
    requested.push(value);
    await route.fulfill({
      json: value
        ? { items: [earlier, old], next_cursor: null }
        : { items: [recent, earlier], next_cursor: cursor },
    });
  });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Price history' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Down $55.00 (18.3%) from the first price shown')).toBeVisible();
  await expect(dialog.getByRole('row')).toHaveCount(3);
  await expect(
    dialog.getByText('Earlier observations are available.', { exact: false }),
  ).toBeVisible();
  await dialog.getByRole('button', { name: 'Load earlier observations' }).click();
  await expect(dialog.getByRole('row')).toHaveCount(4);
  await expect(dialog.locator('.chart-line')).toHaveCount(2);
  await expect(dialog.getByText('Up $135.00 (122.7%) from the first price shown')).toBeVisible();
  await dialog.getByRole('button', { name: 'Past 7 days' }).click();
  await expect(dialog.getByRole('button', { name: 'Past 7 days' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(dialog.getByRole('row')).toHaveCount(3);
  await expect(dialog.getByText('Down $55.00 (18.3%) from the first price shown')).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Export CSV' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(`fareflare-${monitor.id}-prices.csv`);
  const csv = await readFile((await download.path())!, 'utf8');
  expect(csv).toContain('"observed_at_utc","amount_minor","currency"');
  expect(csv).toContain('"24500","USD"');
  expect(csv).toContain(new Date(recent.observed_at * 1000).toISOString());
  expect(csv).not.toContain('11000');
  expect(csv.trim().split('\r\n')).toHaveLength(3);
  expect(requested).toEqual([null, cursor]);
  await dialog.getByRole('button', { name: 'Past 30 days' }).click();
  await expect(dialog.getByRole('row')).toHaveCount(4);
});

test('history distinguishes failed requests, empty ranges and missing observations', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  await page.route('**/history**', (route) =>
    ++attempts === 1
      ? route.fulfill({ status: 503, json: { detail: 'History is temporarily unavailable.' } })
      : route.fulfill({ json: { items: [old] } }),
  );
  await page.goto('/app');
  await page.getByRole('button', { name: 'Price history' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('alert')).toContainText('History is temporarily unavailable.');
  await expect(dialog.getByText('No price recorded yet')).toHaveCount(0);
  await dialog.getByRole('button', { name: 'Try again' }).click();
  await expect(dialog.getByText('One observation so far')).toBeVisible();
  await expect(dialog.locator('.chart-dot')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Past 7 days' }).click();
  await expect(dialog.getByText('No observations in this date range')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'All loaded' }).click();
  await expect(dialog.getByRole('table')).toBeVisible();
  expect(attempts).toBe(2);
});

test('history keeps earlier pages and retries the same cursor after a failure', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  await page.route('**/history**', (route) => {
    if (!new URL(route.request().url()).searchParams.has('cursor')) {
      return route.fulfill({ json: { items: [recent], next_cursor: 'older' } });
    }
    return ++attempts === 1
      ? route.fulfill({ status: 503, json: { detail: 'Could not load earlier prices.' } })
      : route.fulfill({ json: { items: [old] } });
  });
  await page.goto('/app');
  await page.getByRole('button', { name: 'Price history' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Load earlier observations' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Could not load earlier prices.');
  await expect(dialog.getByRole('row')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Load earlier observations' }).click();
  await expect(dialog.getByRole('row')).toHaveCount(3);
  await expect(dialog.getByRole('alert')).toHaveCount(0);
});

test('monitor filters combine route and status without hiding the account quota', async ({
  page,
}) => {
  await mock(page);
  const paused = { ...structuredClone(monitor), id: 'b'.repeat(32), status: 'paused' };
  const stopped = { ...structuredClone(monitor), id: 'c'.repeat(32), status: 'cancelled' };
  await page.route('**/v1/monitors?limit=100', (route) =>
    route.fulfill({ json: { items: [monitor, paused, stopped], active_count: 2 } }),
  );
  await page.goto('/app');
  await expect(page.getByRole('article')).toHaveCount(3);
  await page.getByLabel('Status', { exact: true }).selectOption('paused');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByRole('article')).toContainText('Paused');
  await expect(page.getByLabel('Monitor summary')).toContainText('2 of 3 monitors in use');
  await page.getByLabel('Find a flight').fill('den 414');
  await expect(page.getByRole('article')).toHaveCount(1);
  await page.getByLabel('Find a flight').fill('JFK');
  await expect(page.getByRole('heading', { name: 'No matching flights' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByRole('article')).toHaveCount(3);
  await expect(page.getByLabel('Find a flight')).toHaveValue('');
  await page.getByLabel('Status', { exact: true }).selectOption('attention');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByRole('article')).toContainText('Waiting for an updated price');
  await page.getByLabel('Status', { exact: true }).selectOption('archived');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(page.getByRole('article')).toContainText('Stopped');
});

test('price explorer is accessible at desktop and mobile sizes under the portal CSP', async ({
  page,
}) => {
  await mock(page);
  const cspErrors: string[] = [];
  await page.addInitScript(() => {
    (window as any).violations = [];
    document.addEventListener('securitypolicyviolation', (event) =>
      (window as any).violations.push(event.violatedDirective),
    );
  });
  page.on('pageerror', (error) => cspErrors.push(error.message));
  const prices = [
    32000, 32000, 30000, 29800, 31000, 27500, 27500, 27000, 28500, 25000, 24500, 24500,
  ];
  await page.route('**/history**', (route) =>
    route.fulfill({
      json: {
        items: prices
          .map((amount_minor, index) => ({
            ...observation,
            amount_minor,
            observed_at: now - (12 - index) * 900 - (index < 6 ? 7200 : 0),
          }))
          .reverse(),
      },
    }),
  );
  await page.goto('/app');
  await page.getByRole('button', { name: 'Price history' }).click();
  await expect(page.getByRole('dialog').getByRole('table')).toBeVisible();
  await page.screenshot({ path: 'artifacts/history-desktop.png' });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Export CSV' })).toBeVisible();
  expect(
    await page.getByRole('dialog').evaluate((node) => node.scrollWidth <= node.clientWidth),
  ).toBeTruthy();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: 'artifacts/history-mobile.png' });
  expect(await page.evaluate(() => (window as any).violations)).toEqual([]);
  expect(cspErrors).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Price history' })).toBeFocused();
});
