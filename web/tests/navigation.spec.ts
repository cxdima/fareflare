import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock } from './fixtures';

const pages = ['Account settings', 'Webhooks', 'API & MCP', 'Alert activity', 'Flight monitors'];

test('every page opens at its top and names itself in the browser tab', async ({ page }) => {
  await mock(page);
  // Short enough that every page is taller than the window.
  await page.setViewportSize({ width: 1280, height: 520 });
  await page.goto('/app');
  const navigation = page.getByRole('navigation', { name: 'Main navigation' });
  for (const name of pages) {
    await page.evaluate(() => window.scrollTo(0, 300));
    await navigation.getByRole('link', { name, exact: true }).click();
    await expect(page).toHaveTitle(`${name} · Fareflare`);
    // Focus moves to the page for keyboard users without dragging the scroll with it.
    await expect(page.locator('#main-content')).toBeFocused();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
  }
});

test('changing a settings section keeps the place on the page', async ({ page }) => {
  await mock(page);
  await page.setViewportSize({ width: 1280, height: 520 });
  await page.goto('/app#settings');
  await expect(page.getByRole('heading', { name: 'Time and region' })).toBeVisible();
  // The page rises into place as it opens; click once it has settled, as a person would.
  await page.waitForFunction(() =>
    document.getAnimations().every((animation) => animation.playState !== 'running'),
  );
  await page.evaluate(() => window.scrollTo(0, 120));
  await page
    .getByRole('navigation', { name: 'Settings sections' })
    .getByRole('button', { name: 'Security', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'Password', exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(120);
});

for (const [width, height] of [
  [1280, 800],
  [390, 844],
]) {
  test(`every workspace page passes the accessibility scan at ${width}px`, async ({ page }) => {
    await mock(page);
    await page.setViewportSize({ width, height });
    await page.goto('/app');
    const navigation = page.getByRole('navigation', { name: 'Main navigation' });
    for (const name of pages) {
      await navigation.getByRole('link', { name, exact: true }).click();
      await expect(page.locator('main h1')).toBeVisible();
      const { violations } = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze();
      expect(violations, name).toEqual([]);
    }
  });
}

test('the header reports system status, and its Refresh reloads the page being viewed', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#alerts');
  const status = page.getByRole('banner').getByRole('link', { name: /All systems working/ });
  await expect(status).toHaveAttribute('href', '/status');
  await expect(status).toHaveAttribute('data-status', 'operational');
  await expect(page.getByRole('heading', { level: 1, name: 'Alert activity' })).toBeVisible();
  // One Refresh on the page, and it reloads the alerts too.
  await expect(page.getByRole('button', { name: /Refresh/ })).toHaveCount(1);
  const alertReads = () => calls.filter((call) => call.path === '/v1/alerts').length;
  await expect.poll(alertReads).toBe(1);
  await page.getByRole('button', { name: 'Refresh dashboard', exact: true }).click();
  await expect.poll(alertReads).toBe(2);

  // Trouble is said in words, not only in colour.
  await page.route('**/v1/status', (route) =>
    route.fulfill({
      json: {
        status: 'major',
        updated_at: 0,
        window_hours: 24,
        components: [],
        hours: [],
      },
    }),
  );
  await page.getByRole('button', { name: 'Refresh dashboard', exact: true }).click();
  await expect(
    page.getByRole('banner').getByRole('link', { name: /Price checks are not working/ }),
  ).toHaveAttribute('data-status', 'major');
});
