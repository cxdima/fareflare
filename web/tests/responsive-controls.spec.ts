import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock } from './fixtures';

test('mobile alert rows keep the price and retry action reachable without horizontal scrolling', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/app#alerts');
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('cell', { name: '$245.00', exact: true })).toBeVisible();
  const retry = page.getByRole('button', { name: 'Retry delivery for DEN → DFW' });
  await expect(retry).toBeVisible();
  const bounds = await retry.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(375);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await retry.click();
  expect(
    calls.some((call) => call.path === '/v1/alerts/alert/retry' && call.method === 'POST'),
  ).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('the mobile script-free API reference keeps endpoint text inside its readable margins', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/docs');
  await expect(page.getByRole('heading', { name: 'Fareflare API reference' })).toBeVisible();
  await expect(page.locator('script')).toHaveCount(0);
  const endpoint = page.getByRole('cell', {
    name: '/v1/preferences/telegram-preview',
    exact: true,
  });
  await expect(endpoint).toBeVisible();
  const measures = await page.evaluate(() => {
    const main = document.querySelector('main')!.getBoundingClientRect();
    const table = document.querySelector('table')!;
    return {
      left: main.left,
      right: main.right,
      overflow: document.documentElement.scrollWidth > innerWidth,
      clippedCells: [...table.querySelectorAll('td')].some(
        (cell) => cell.scrollWidth > cell.clientWidth + 1,
      ),
    };
  });
  expect(measures.left).toBeGreaterThanOrEqual(16);
  expect(measures.right).toBeLessThanOrEqual(359);
  expect(measures.overflow).toBe(false);
  expect(measures.clippedCells).toBe(false);
});
