import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { fakePasskeys, mock } from './fixtures';

const sections = (page: Page) => page.getByRole('navigation', { name: 'Settings sections' });
const section = (page: Page, name: string) =>
  sections(page).getByRole('button', { name, exact: true });
const axe = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze())
    .violations;

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
  await page.getByRole('button', { name: 'Forgot password?', exact: true }).click();
  await expect(page).toHaveURL('/forgot-password#settings?section=security');
  await page.getByRole('button', { name: 'Back to sign in' }).click();
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
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
  const opener = page.locator('[aria-controls="password-drawer"]');
  await expect(opener).toHaveAttribute('aria-expanded', 'false');
  await opener.click();
  await expect(opener).toHaveAttribute('aria-expanded', 'true');
  const current = page.getByLabel('Current password', { exact: true });
  const next = page.getByLabel('New password', { exact: true });
  const change = page.getByRole('button', { name: 'Change password', exact: true });
  const sent = () => calls.filter((call) => call.path === '/auth/password');

  await expect(current).toHaveAttribute('autocomplete', 'current-password');
  await expect(next).toHaveAttribute('autocomplete', 'new-password');
  await expect(next).toHaveAttribute('passwordrules', 'minlength: 15; maxlength: 128;');
  // The saved login this change belongs to, for a password manager; not a field to fill.
  const owner = page.locator('#password-drawer input[autocomplete="username"]');
  await expect(owner).toHaveValue('traveler@example.com');
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
  expect(await axe(page)).toEqual([]);

  await next.fill('another-long-private-password');
  await change.click();
  await expect(page.getByRole('status').filter({ hasText: 'Password changed' })).toBeVisible();
  // The drawer closes, and what was typed is gone with it.
  await expect(opener).toHaveAttribute('aria-expanded', 'false');
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
  await page.locator('[aria-controls="password-drawer"]').click();
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
  await expect(page.getByRole('status').filter({ hasText: 'Password changed' })).toHaveCount(0);
  expect(attempts).toBe(1);
});

test('two-step sign-in is set up with a QR code, a key to type, and backup codes shown once', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  await page.getByRole('button', { name: 'Set up', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByText('Enter your password.', { exact: true })).toBeVisible();
  await page.getByLabel('Confirm your password to begin').fill('a-long-private-password');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();

  await expect(
    page.getByRole('img', { name: 'QR code to add Fareflare to an authenticator app' }),
  ).toBeVisible();
  await expect(page.locator('.setup-secret code')).toHaveText(
    'JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP',
  );
  await expect(
    page.getByRole('link', { name: 'On this phone? Open it in your app' }),
  ).toHaveAttribute('href', /^otpauth:\/\/totp\/Fareflare:/);
  const code = page.getByLabel(/Enter the 6-digit code/);
  await expect(code).toHaveAttribute('autocomplete', 'one-time-code');
  expect(await axe(page)).toEqual([]);
  await code.fill('000000');
  await page.getByRole('button', { name: 'Turn on two-step sign-in', exact: true }).click();
  await expect(page.locator('#setup-drawer').getByRole('alert')).toHaveText(
    'That code is not correct',
  );
  await code.fill('123456');
  await page.getByRole('button', { name: 'Turn on two-step sign-in', exact: true }).click();

  const codes = page.getByRole('region', { name: 'Save your backup codes' });
  await expect(codes.getByRole('listitem')).toHaveCount(5);
  await expect(codes.getByRole('listitem').first()).toHaveText('ab2c-de3f');
  await expect(page.locator('#two-step-title + .security-value .status')).toHaveText('On');
  expect(calls.find((call) => call.path === '/auth/two-factor/setup')!.body).toEqual({
    password: 'a-long-private-password',
  });
  await codes.getByRole('button', { name: 'I’ve saved them' }).click();
  await expect(codes).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Turn off', exact: true })).toBeVisible();
});

test('passkeys are added, renamed and removed from the security page', async ({ page }) => {
  await fakePasskeys(page);
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  const list = page.locator('.passkey-list');
  await expect(list).toContainText('No passkeys yet.');
  await page.getByRole('button', { name: 'Add a passkey', exact: true }).click();
  await expect(list.getByRole('heading', { name: '1Password', exact: true })).toBeVisible();
  await expect(
    page.getByRole('status').filter({ hasText: 'Passkey added: 1Password' }),
  ).toBeVisible();
  const added = calls.find((call) => call.path === '/auth/passkeys' && call.method === 'POST')!;
  expect(added.body.challenge_id).toBe('challenge-test');
  expect(added.body.credential.response.transports).toEqual(['internal', 'hybrid']);

  await page.getByRole('button', { name: 'Rename 1Password' }).click();
  await page.getByLabel('Passkey name').fill('Work laptop');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(list.getByRole('heading', { name: 'Work laptop', exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Remove Work laptop' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Work laptop will no longer sign in to Fareflare.');
  await dialog.getByRole('button', { name: 'Remove passkey' }).click();
  await expect(list).toContainText('No passkeys yet.');
});

test('the email can be changed with the password, and must be confirmed again', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  await expect(page.locator('.security-value .status').first()).toHaveText('Confirmed');
  await page.locator('[aria-controls="email-drawer"]').click();
  await page.getByLabel('New email').fill('traveler@work.example.com');
  await page.getByLabel('Your password').first().fill('a-long-private-password');
  await page.getByRole('button', { name: 'Save email', exact: true }).click();
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: 'We sent a confirmation link to traveler@work.example.com.' }),
  ).toBeVisible();
  await expect(page.locator('.security-value .status').first()).toHaveText('Not confirmed');
  await page.getByRole('button', { name: 'Send a new confirmation link' }).click();
  await expect(page.getByText('Sent. It works for 24 hours.')).toBeVisible();
  expect(calls.filter((call) => call.path === '/auth/email/resend')).toHaveLength(1);
});

test('signing out everywhere asks for the password and keeps this browser signed in', async ({
  page,
}) => {
  const calls = await mock(page);
  await page.goto('/app#settings?section=security');
  await page.locator('[aria-controls="everywhere-drawer"]').click();
  await page.locator('#everywhere-password').fill('a-long-private-password');
  await page
    .locator('#everywhere-drawer')
    .getByRole('button', { name: 'Sign out everywhere' })
    .click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Every other browser is signed out' }),
  ).toBeVisible();
  await expect(page).toHaveURL('/app#settings?section=security');
  expect(calls.find((call) => call.path === '/auth/sign-out-everywhere')!.body).toEqual({
    password: 'a-long-private-password',
  });
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
