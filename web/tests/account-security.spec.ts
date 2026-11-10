import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock } from './fixtures';

const sections = (page: Page) => page.getByRole('navigation', { name: 'Settings sections' });
const section = (page: Page, name: string) =>
  sections(page).getByRole('button', { name, exact: true });

test('a settings section has an address that survives a reload', async ({ page }) => {
  await mock(page);
  await page.goto('/app#settings?section=security');
  await expect(section(page, 'Security')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: 'Password', exact: true })).toBeVisible();
  await section(page, 'Connections').click();
  await expect(page).toHaveURL('/app#settings?section=connections');
  await page.reload();
  await expect(section(page, 'Connections')).toHaveAttribute('aria-pressed', 'true');
  // An unknown section falls back instead of showing an empty page.
  await page.goto('/app#settings?section=nonsense');
  await page.reload();
  await expect(section(page, 'Display')).toHaveAttribute('aria-pressed', 'true');
});

test('someone sent to sign in from a workspace page arrives on that page', async ({ page }) => {
  await mock(page, false);
  await page.goto('/app#settings?section=security');
  await expect(page).toHaveURL('/login#settings?section=security');
  // Changing to another sign-in page does not lose the destination either.
  await page.getByRole('button', { name: 'Forgot your password?', exact: true }).click();
  await expect(page).toHaveURL('/recover#settings?section=security');
  await page.getByRole('button', { name: 'Already have an account? Sign in' }).click();
  await page.getByLabel('Email or username', { exact: true }).fill('traveler');
  await page.getByLabel('Password', { exact: true }).fill('a-long-private-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL('/app#settings?section=security');
  await expect(section(page, 'Security')).toHaveAttribute('aria-pressed', 'true');

  // Signing out on purpose starts the next visit from the top.
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL('/login');
});

test('changing a password validates first, confirms plainly, and is readable by a password manager', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  const current = page.getByLabel('Current password', { exact: true });
  const next = page.getByLabel('New password', { exact: true });
  const change = page.getByRole('button', { name: 'Change password', exact: true });
  const sent = () => calls.filter((call) => call.path === '/auth/password');

  await expect(current).toHaveAttribute('autocomplete', 'current-password');
  await expect(next).toHaveAttribute('autocomplete', 'new-password');
  await expect(next).toHaveAttribute('passwordrules', 'minlength: 15; maxlength: 128;');
  // The saved login this change belongs to, for a password manager; not a field to fill.
  const owner = page.locator('.security-form input[autocomplete="username"]');
  await expect(owner).toHaveValue('traveler');
  await expect(owner).toHaveAttribute('readonly', '');
  await expect(owner).toHaveAttribute('tabindex', '-1');

  await change.click();
  await expect(page.getByText('Enter your current password.', { exact: true })).toBeVisible();
  await expect(page.getByText('Enter a new password.', { exact: true })).toBeVisible();
  await expect(current).toBeFocused();
  await expect(current).toHaveAttribute('aria-invalid', 'true');
  await current.fill('a-long-private-password');
  await next.fill('too short');
  await change.click();
  await expect(page.getByText('Use at least 15 characters.', { exact: true })).toBeVisible();
  await expect(next).toBeFocused();
  expect(sent()).toEqual([]);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  await next.fill('another-long-private-password');
  await change.click();
  await expect(page.getByRole('status').filter({ hasText: 'Password changed.' })).toBeVisible();
  expect(sent()).toHaveLength(1);
  expect(sent()[0]).toMatchObject({
    method: 'POST',
    csrf: 'csrf-test',
    body: {
      current_password: 'a-long-private-password',
      new_password: 'another-long-private-password',
    },
  });
  await expect(current).toHaveValue('');
  await expect(next).toHaveValue('');
  await expect(page.getByText('Enter your current password.', { exact: true })).toHaveCount(0);
  expect(
    await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
  ).toEqual({ local: 0, session: 0 });
});

test('a mistyped current password is an error on the page, not a signed-out session', async ({
  page,
}) => {
  await mock(page);
  let attempts = 0;
  await page.route('**/auth/password', (route) => {
    attempts += 1;
    return route.fulfill({ status: 403, json: { detail: 'That password is not correct' } });
  });
  await page.goto('/app#settings?section=security');
  await page.getByLabel('Current password', { exact: true }).fill('not-my-real-password');
  await page.getByLabel('New password', { exact: true }).fill('another-long-private-password');
  await page.getByRole('button', { name: 'Change password', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('That password is not correct');
  await expect(page).toHaveURL('/app#settings?section=security');
  await expect(page.getByRole('heading', { name: 'Account settings', exact: true })).toBeVisible();
  // What was typed is kept, so only the mistake needs fixing.
  await expect(page.getByLabel('New password', { exact: true })).toHaveValue(
    'another-long-private-password',
  );
  await expect(page.getByRole('status').filter({ hasText: 'Password changed.' })).toHaveCount(0);
  expect(attempts).toBe(1);
});

test('a new recovery code asks for the password, shows the code once, and can be cancelled', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  const start = page.getByRole('button', { name: 'Create a new recovery code', exact: true });
  const sent = () => calls.filter((call) => call.path === '/auth/recovery-code');

  await start.click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(start).toBeVisible();

  await start.click();
  const confirm = page.getByLabel('Confirm your password', { exact: true });
  await expect(confirm).toHaveAttribute('autocomplete', 'current-password');
  await expect(
    page.getByText('Your current recovery code stops working straight away.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Create new code', exact: true }).click();
  expect(sent()).toEqual([]);
  await confirm.fill('a-long-private-password');
  await page.getByRole('button', { name: 'Create new code', exact: true }).click();

  const code = page.getByRole('region', { name: 'Your new recovery code', exact: true });
  await expect(code.getByRole('textbox')).toHaveValue('replacement-recovery');
  await expect(code.getByText(/The old code no longer works\./)).toBeVisible();
  expect(sent()).toHaveLength(1);
  expect(sent()[0]).toMatchObject({
    method: 'POST',
    csrf: 'csrf-test',
    body: { password: 'a-long-private-password' },
  });
  await expect(confirm).toHaveCount(0);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await code.getByRole('button', { name: 'I’ve saved it', exact: true }).click();
  await expect(page.getByText('replacement-recovery')).toHaveCount(0);
  await expect(start).toBeVisible();
});

test('deleting an account with the wrong password keeps the account and the session', async ({
  page,
}) => {
  await mock(page);
  await page.route('**/v1/account', (route) =>
    route.request().method() === 'DELETE'
      ? route.fulfill({ status: 403, json: { detail: 'That password is not correct' } })
      : route.fallback(),
  );
  await page.goto('/app#settings?section=security');
  await page.getByRole('button', { name: 'Delete my account', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Confirm password', { exact: true }).fill('not-my-real-password');
  await dialog.getByRole('button', { name: 'Permanently delete account' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('That password is not correct');
  await expect(page).toHaveURL('/app#settings?section=security');
});
