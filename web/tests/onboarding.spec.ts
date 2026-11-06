import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('registration explains invalid fields, focuses the first error, and never submits invalid input', async ({
  page,
}) => {
  const submissions: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/auth/')) {
      submissions.push(request.url());
    }
  });
  await page.goto('/register?invite=local-invitation-example');
  await page.getByLabel('Username', { exact: true }).fill('invalid name');
  await page.getByLabel('Password', { exact: true }).fill('too short');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Use at least 15 characters.', { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      'Use 3–40 letters, numbers, periods, underscores or hyphens. Start with a letter or number.',
    ),
  ).toBeVisible();
  await expect(page.getByLabel('Username', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Username', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );

  await page.getByLabel('Username', { exact: true }).fill('valid.traveler');
  await page.getByLabel('Password', { exact: true }).fill('long-local-test-password');
  await page.getByLabel('Invitation code', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(
    page.getByText('Enter the invitation code from your link.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Invitation code', { exact: true })).toBeFocused();
  expect(submissions).toEqual([]);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test('password visibility is accessible and changing auth mode clears the password and validation state', async ({
  page,
}) => {
  await page.goto('/login');
  const password = page.getByLabel('Password', { exact: true });
  await password.fill('local-test-password');
  await expect(password).toHaveAttribute('type', 'password');
  await page.getByRole('button', { name: 'Show password', exact: true }).click();
  await expect(password).toHaveAttribute('type', 'text');
  await expect(password).toHaveValue('local-test-password');
  await page.getByRole('button', { name: 'Hide password', exact: true }).click();
  await expect(password).toHaveAttribute('type', 'password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByText('Enter your username.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Forgot your password?', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Recover your account', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('New password', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('New password', { exact: true })).toHaveAttribute(
    'type',
    'password',
  );
  await expect(page.getByText('Enter your username.', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(
    page.getByText('Enter the recovery code you saved when you signed up.', { exact: true }),
  ).toBeVisible();
});

test('sign-in shows pending feedback and retains entered values after a server failure', async ({
  page,
}) => {
  let completeRequest: (() => void) | undefined;
  const responseReady = new Promise<void>((resolve) => {
    completeRequest = resolve;
  });
  let submissions = 0;
  await page.route('**/auth/login', async (route) => {
    submissions += 1;
    await responseReady;
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Invalid username or password' }),
    });
  });
  await page.goto('/login');
  await page.getByLabel('Username', { exact: true }).fill('traveler');
  await page.getByLabel('Password', { exact: true }).fill('local-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const pending = page.getByRole('button', { name: 'Signing in…', exact: true });
  await expect(pending).toBeDisabled();
  await expect(pending).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByRole('button', { name: 'Forgot your password?', exact: true }),
  ).toBeDisabled();
  completeRequest!();
  await expect(page.getByRole('alert')).toHaveText('Invalid username or password');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Username', { exact: true })).toHaveValue('traveler');
  await expect(page.getByLabel('Password', { exact: true })).toHaveValue('local-test-password');
  expect(submissions).toBe(1);
});

test('public answers work with the keyboard and guide contents link to real sections', async ({
  page,
}) => {
  await page.goto('/');
  const question = page
    .locator('summary')
    .filter({ hasText: 'Do I need to connect my Google account?' });
  const answer = page.getByText(
    'No. Paste a supported Google Flights link. Fareflare checks the public price without accessing your Google account.',
    { exact: true },
  );
  await expect(answer).toBeHidden();
  await question.focus();
  await page.keyboard.press('Enter');
  await expect(answer).toBeVisible();
  await page.keyboard.press('Space');
  await expect(answer).toBeHidden();
  await page.goto('/guides/reading-flight-price-alerts');
  const contents = page.getByRole('navigation', { name: 'On this page' });
  await expect(contents).toBeVisible();
  const sectionLink = contents.getByRole('link').first();
  const heading = await sectionLink.innerText();
  await sectionLink.click();
  await expect(page).toHaveURL(/#section-0$/);
  await expect(
    page.locator('#section-0').getByRole('heading', { name: heading, exact: true }),
  ).toBeInViewport();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
