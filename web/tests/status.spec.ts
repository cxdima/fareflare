import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.use({ timezoneId: 'America/Chicago' });

const HOUR = 3600;
const now = Math.floor(Date.now() / 1000);
const thisHour = now - (now % HOUR);

type Level = 'operational' | 'degraded' | 'major' | 'none';

function hours(pattern: (index: number) => Level) {
  return Array.from({ length: 24 }, (_, index) => {
    const status = pattern(index);
    const failed = { operational: 1, degraded: 6, major: 11, none: 0 }[status];
    return {
      start: thisHour - (23 - index) * HOUR,
      runs: status === 'none' ? 0 : 60,
      collected: status === 'none' ? 0 : 12 - failed,
      failed,
      alerts_sent: status === 'operational' && index % 6 === 0 ? 1 : 0,
      status,
    };
  });
}

function report(
  status: string,
  checks: Record<string, unknown>,
  alerts: Record<string, unknown>,
  pattern: (index: number) => Level = () => 'operational',
) {
  const list = hours(pattern);
  const total = list.reduce((sum, hour) => sum + hour.collected + hour.failed, 0);
  return {
    status,
    updated_at: now,
    window_hours: 24,
    components: [
      { id: 'website', status: 'operational', reason: null },
      {
        id: 'price_checks',
        status: 'operational',
        reason: null,
        last_run_at: now - 40,
        checks: total,
        succeeded: list.reduce((sum, hour) => sum + hour.collected, 0),
        ...checks,
      },
      {
        id: 'alerts',
        status: 'operational',
        reason: null,
        sent: list.reduce((sum, hour) => sum + hour.alerts_sent, 0),
        ...alerts,
      },
    ],
    hours: list,
  };
}

async function serve(page: Page, body: () => unknown, status = () => 200) {
  const reads = { count: 0 };
  await page.route('**/v1/status', (route) => {
    reads.count += 1;
    return route.fulfill({
      status: status(),
      contentType: 'application/json',
      body: JSON.stringify(body()),
    });
  });
  return reads;
}

const scan = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze())
    .violations;

test('the status page says everything is working, and how that was measured', async ({ page }) => {
  await serve(page, () => report('operational', {}, {}));
  await page.goto('/status');
  await expect(page).toHaveTitle('System status — Fareflare');
  await expect(page.getByRole('heading', { level: 1, name: 'System status' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Everything is working' })).toBeVisible();
  await expect(page.getByText(/Updated at \d{1,2}:\d{2}/)).toBeVisible();

  const services = page.getByRole('list').filter({ hasText: 'Website and API' });
  const rows = services.getByRole('listitem');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('Working');
  await expect(rows.nth(1)).toContainText('Price checks');
  await expect(rows.nth(1)).toContainText(
    '264 of 288 checks recorded a price in the last 24 hours',
  );
  await expect(rows.nth(2)).toContainText('4 alerts sent in the last 24 hours.');

  // Twenty-four hours, each one readable without seeing its colour.
  const bars = page.locator('.status-hours li');
  await expect(bars).toHaveCount(24);
  await expect(bars.last().locator('.visually-hidden')).toHaveText(
    /: 11 of 12 checks recorded a price$/,
  );
  await page.getByText('Hour by hour', { exact: true }).click();
  await expect(page.getByRole('row')).toHaveCount(25);
  await expect(page.getByRole('columnheader', { name: 'Could not finish' })).toBeVisible();
  await expect(page.locator('[style]')).toHaveCount(0);
  expect(await scan(page)).toEqual([]);

  // Both footers lead here.
  await expect(
    page.getByRole('contentinfo').getByRole('link', { name: 'System status' }),
  ).toHaveAttribute('href', '/status');
});

test('trouble is named plainly: failing checks, then checks that stopped', async ({ page }) => {
  let current = report('degraded', { status: 'degraded', reason: 'failing' }, {}, (index) =>
    index > 20 ? 'degraded' : 'operational',
  );
  await serve(page, () => current);
  await page.goto('/status');
  await expect(page.getByRole('heading', { name: 'Some price checks are failing' })).toBeVisible();
  const checks = page.getByRole('listitem').filter({ hasText: 'Price checks' }).first();
  await expect(checks).toContainText('Having trouble');
  await expect(checks).toContainText('prices may arrive late');
  await expect(page.locator('.status-hours li[data-status="degraded"]')).toHaveCount(3);
  expect(await scan(page)).toEqual([]);

  current = report(
    'major',
    { status: 'major', reason: 'stalled', last_run_at: now - 2 * HOUR },
    { status: 'major', reason: 'stalled' },
    (index) => (index > 21 ? 'none' : 'operational'),
  );
  await page.getByRole('button', { name: 'Check again' }).click();
  await expect(page.getByRole('heading', { name: 'Price checks are not running' })).toBeVisible();
  await expect(checks).toContainText('Not working');
  await expect(checks).toContainText('Prices and alerts are paused until checks resume.');
  await expect(
    page.getByRole('listitem').filter({ hasText: 'so they are paused too' }),
  ).toBeVisible();
  await expect(page.locator('.status-hours li').last().locator('.visually-hidden')).toHaveText(
    /: no record$/,
  );
  expect(await scan(page)).toEqual([]);

  current = report('major', { status: 'major', reason: 'failing' }, {}, () => 'major');
  await page.getByRole('button', { name: 'Check again' }).click();
  await expect(page.getByRole('heading', { name: 'Most price checks are failing' })).toBeVisible();
});

test('a new installation and a failed load each say what is known', async ({ page }) => {
  let code = 503;
  await serve(
    page,
    () =>
      report(
        'unknown',
        { status: 'unknown', last_run_at: null },
        { status: 'unknown' },
        () => 'none',
      ),
    () => code,
  );
  await page.goto('/status');
  const alert = page.getByRole('alert');
  await expect(
    alert.getByRole('heading', { name: 'The status could not be loaded' }),
  ).toBeVisible();
  expect(await scan(page)).toEqual([]);

  code = 200;
  await alert.getByRole('button', { name: 'Try again' }).click();
  await expect(
    page.getByRole('heading', { name: 'No price checks have been recorded yet' }),
  ).toBeVisible();
  await expect(
    page.getByRole('listitem').filter({ hasText: 'Price checks' }).first(),
  ).toContainText('No record yet');

  // A refresh that fails keeps the last report and says so.
  code = 503;
  await page.getByRole('button', { name: 'Check again' }).click();
  await expect(page.getByText('The latest refresh did not get through.')).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'No price checks have been recorded yet' }),
  ).toBeVisible();
});

test('the page refreshes by itself while it is open, and fits a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.clock.install();
  const reads = await serve(page, () => report('operational', {}, {}));
  await page.goto('/status');
  await expect(page.getByRole('heading', { name: 'Everything is working' })).toBeVisible();
  const before = reads.count;
  await page.clock.runFor(61000);
  await expect.poll(() => reads.count).toBe(before + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  expect(await scan(page)).toEqual([]);
});
