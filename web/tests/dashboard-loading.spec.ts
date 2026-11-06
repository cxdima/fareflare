import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock, monitor } from './fixtures';

function gate() {
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { pending, release };
}

test('refresh keeps its visible label in the accessible name while the initial request is pending', async ({
  page,
}) => {
  await mock(page);
  const monitors = gate();
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    await monitors.pending;
    await route.fulfill({ json: { items: [monitor], active_count: 1 } });
  });
  await page.goto('/app');
  try {
    const pending = page.getByRole('button', { name: 'Refreshing dashboard', exact: true });
    await expect(pending).toHaveText('Refreshing…');
    await expect(pending).toBeDisabled();
    expect(
      (
        await new AxeBuilder({ page })
          .include('.refresh-button')
          .withRules(['label-content-name-mismatch'])
          .analyze()
      ).violations,
    ).toEqual([]);
  } finally {
    monitors.release();
  }
  const refreshed = page.getByRole('button', { name: 'Refresh dashboard', exact: true });
  await expect(refreshed).toHaveText('Refresh');
  await expect(refreshed).toBeEnabled();
  await expect(page.getByRole('article')).toHaveCount(1);
});

test('external hash navigation works before and after initial workspace and preference requests settle', async ({
  page,
}) => {
  await mock(page);
  const monitors = gate();
  const preferences = gate();
  const monitorsStarted = gate();
  const preferencesStarted = gate();
  await page.route(/\/v1\/monitors(?:\?|$)/, async (route) => {
    monitorsStarted.release();
    await monitors.pending;
    await route.fulfill({ json: { items: [monitor], active_count: 1 } });
  });
  await page.route('**/v1/preferences', async (route) => {
    preferencesStarted.release();
    await preferences.pending;
    await route.fulfill({ json: { muted: false, muted_routes: [] } });
  });
  await page.goto('/app');
  try {
    await Promise.all([monitorsStarted.pending, preferencesStarted.pending]);
    // Same-document navigation exercises hashchange, not the sidebar's select handler.
    await page.goto('/app#settings');
    await expect(
      page.getByRole('heading', { name: 'Account settings', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('Loading your preferences…', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Refreshing dashboard' })).toBeDisabled();

    monitors.release();
    await expect(
      page.getByRole('button', { name: 'Refresh dashboard', exact: true }),
    ).toBeEnabled();
    await page.goto('/app#alerts');
    await expect(page.getByRole('heading', { name: 'Alert activity', exact: true })).toBeVisible();
  } finally {
    monitors.release();
    preferences.release();
  }
  await page.goto('/app#settings');
  await expect(page.getByLabel('Time zone', { exact: true })).toBeVisible();
  await page.goto('/app#developer');
  await expect(page.getByRole('heading', { name: 'API & MCP', exact: true })).toBeVisible();
  await page.goto('/app#monitors');
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toBeVisible();
  await expect(page.getByRole('article')).toHaveCount(1);
});

test('leaving the dashboard during session bootstrap does not start late workspace reads or polling', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.clock.install();
  const account = gate();
  const accountStarted = gate();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/v1/account', async (route) => {
    accountStarted.release();
    await account.pending;
    await route.fulfill({
      json: { account: { id: 'user', username: 'traveler' }, csrf_token: 'csrf-test' },
    });
  });
  await page.goto('/app');
  const response = page.waitForResponse('**/v1/account');
  try {
    await accountStarted.pending;
    await expect(page.getByRole('heading', { name: 'Loading your workspace…' })).toBeVisible();
    // Router history navigation destroys the component without replacing the document.
    await page.evaluate(() => {
      history.pushState(null, '', '/about');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    await expect(page.locator('ff-public')).toBeVisible();
    await expect(page.locator('ff-dashboard')).toHaveCount(0);
  } finally {
    account.release();
  }
  await (await response).finished();
  // Virtual time crosses the polling interval without a real sleep.
  await page.clock.runFor(61000);
  expect(calls.filter((call) => ['/v1/monitors', '/v1/preferences'].includes(call.path))).toEqual(
    [],
  );
  await expect(page).toHaveURL('/about');
  await expect(page.locator('ff-public')).toBeVisible();
  expect(errors).toEqual([]);
});
