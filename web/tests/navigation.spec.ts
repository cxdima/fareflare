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
