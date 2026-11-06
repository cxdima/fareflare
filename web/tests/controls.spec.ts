import { expect, test } from '@playwright/test';
import { flightUrl, mock } from './fixtures';

test('flight rule selection works by keyboard and closing its picker preserves the dialog', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app');
  await page.getByRole('button', { name: 'Watch a flight', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const rule = dialog.getByLabel('Notify me when', { exact: true });

  await rule.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(rule).toHaveValue('below_price');
  await expect(rule).toBeFocused();
  await expect(dialog.getByLabel('Target total (USD)')).toBeVisible();

  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowUp');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  await expect(rule).toHaveValue('below_price');
  await expect(rule).toBeFocused();

  await dialog.getByLabel('Google Flights link').fill(flightUrl);
  await dialog.getByLabel('Target total (USD)').fill('225.50');
  await dialog.getByRole('button', { name: 'Start watching', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const created = calls.find((call) => call.path === '/v1/monitors' && call.method === 'POST');
  expect(created?.body.policy).toMatchObject({ kind: 'below_price', threshold_minor: 22550 });
});
