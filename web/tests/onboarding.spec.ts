import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock } from './fixtures';

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
  await page.getByLabel('Email or username', { exact: true }).fill('invalid name');
  await page.getByLabel('Password', { exact: true }).fill('too short');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Use at least 15 characters.', { exact: true })).toBeVisible();
  await expect(
    page.getByText(
      'Use an email address, or a username of 3–40 letters, numbers, periods, underscores or hyphens.',
    ),
  ).toBeVisible();
  await expect(page.getByLabel('Email or username', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Email or username', { exact: true })).toHaveAttribute(
    'aria-invalid',
    'true',
  );

  // An address is as good a sign-in name as a username: it is what a password manager offers.
  await page.getByLabel('Email or username', { exact: true }).fill('traveler@example.com');
  await page.getByLabel('Password', { exact: true }).fill('long-local-test-password');
  await expect(page.getByText(/Use an email address, or a username/)).toHaveCount(0);
  await page.getByLabel('Email or username', { exact: true }).fill('valid.traveler');
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
  await expect(page.getByText('Enter your email or username.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Forgot your password?', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Recover your account', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('New password', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('New password', { exact: true })).toHaveAttribute(
    'type',
    'password',
  );
  await expect(page.getByText('Enter your email or username.', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reset password', exact: true }).click();
  await expect(
    page.getByText('Enter the recovery code you saved when you signed up.', { exact: true }),
  ).toBeVisible();
  // Recovery is a page of its own, so Back returns to sign-in instead of leaving the site.
  await expect(page).toHaveURL('/recover');
  await page.goBack();
  await expect(page).toHaveURL('/login');
  await expect(page.getByRole('heading', { name: 'Welcome back', exact: true })).toBeVisible();
});

test('each sign-in page tells a password manager what its fields are', async ({ page }) => {
  await mock(page, false);
  await page.goto('/login');
  await expect(page).toHaveTitle('Sign in · Fareflare');
  const name = page.getByLabel('Email or username', { exact: true });
  const password = page.locator('#password');
  await expect(name).toHaveAttribute('autocomplete', 'username');
  await expect(name).toHaveAttribute('inputmode', 'email');
  await expect(password).toHaveAttribute('autocomplete', 'current-password');
  await expect(password).not.toHaveAttribute('passwordrules', /.*/);

  // What was typed follows the visitor to the page they meant to open.
  await name.fill('Traveler@Example.com');
  await page.getByRole('button', { name: 'Create an account', exact: true }).click();
  await expect(page).toHaveURL('/register');
  await expect(page).toHaveTitle('Create your account · Fareflare');
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeFocused();
  await expect(name).toHaveValue('Traveler@Example.com');
  await expect(name).toHaveAttribute('autocomplete', 'username');
  await expect(password).toHaveAttribute('autocomplete', 'new-password');
  await expect(password).toHaveAttribute('passwordrules', 'minlength: 15; maxlength: 128;');
  await expect(password).toHaveValue('');

  await page.goto('/recover');
  await expect(page).toHaveTitle('Recover your account · Fareflare');
  await expect(password).toHaveAttribute('autocomplete', 'new-password');
  await expect(page.getByLabel('Recovery code', { exact: true })).toHaveAttribute(
    'autocomplete',
    'off',
  );
});

test('older invitation links open sign-up, and the invitation survives a change of mind', async ({
  page,
}) => {
  await mock(page, false);
  await page.goto('/login?invite=local-invitation-example');
  await expect(page).toHaveURL('/register?invite=local-invitation-example');
  await expect(page.getByLabel('Invitation code', { exact: true })).toHaveValue(
    'local-invitation-example',
  );
  await page.getByRole('button', { name: 'Already have an account? Sign in' }).click();
  await expect(page).toHaveURL('/login?invite=local-invitation-example');
  await expect(page.getByRole('heading', { name: 'Welcome back', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Create an account', exact: true }).click();
  await expect(page.getByLabel('Invitation code', { exact: true })).toHaveValue(
    'local-invitation-example',
  );

  await page.goto('/?invite=local-invitation-example');
  await expect(page).toHaveURL('/register?invite=local-invitation-example');
});

test('signing up with an email address shows the recovery code once, before the workspace', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/register?invite=local-invitation-example');
  await page.getByLabel('Email or username', { exact: true }).fill('  traveler@example.com ');
  await page.getByLabel('Password', { exact: true }).fill('long-local-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();

  const heading = page.getByRole('heading', { name: 'Save your recovery code', exact: true });
  await expect(heading).toBeFocused();
  await expect(page).toHaveTitle('Save your recovery code · Fareflare');
  expect(calls.find((call) => call.path === '/auth/register')!.body).toEqual({
    username: 'traveler@example.com',
    password: 'long-local-test-password',
    invite_token: 'local-invitation-example',
  });
  await expect(
    page.getByRole('textbox', { name: 'Fareflare recovery code', exact: true }),
  ).toHaveValue('once-only-recovery');
  await expect(page.getByLabel('Password', { exact: true })).toHaveCount(0);
  // Closing the tab now would lose the only copy, so the browser is asked to confirm.
  const leaving = () =>
    page.evaluate(() => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    });
  expect(await leaving()).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  await page.getByRole('button', { name: 'I’ve saved it, continue', exact: true }).click();
  await expect(page).toHaveURL('/app');
  await expect(
    page.getByRole('heading', { name: 'Which flight are you watching?', exact: true }),
  ).toBeVisible();
  expect(await leaving()).toBe(false);
  await expect(page.getByText('once-only-recovery')).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: /recovery code/i })).toHaveCount(0);
});

test('the website sends new visitors to sign-up and returning ones to sign-in', async ({
  page,
}) => {
  await mock(page, false);
  await page.goto('/');
  await page.getByRole('link', { name: 'Start tracking a flight' }).first().click();
  await expect(page).toHaveURL('/register');
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();
  await page.goto('/');
  await page.getByRole('link', { name: 'Already have an account?' }).click();
  await expect(page).toHaveURL('/login');
  await page.goto('/');
  await page.getByRole('navigation').getByRole('link', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL('/login');
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
      body: JSON.stringify({ detail: 'Incorrect email, username or password' }),
    });
  });
  await page.goto('/login');
  await page.getByLabel('Email or username', { exact: true }).fill('traveler');
  await page.getByLabel('Password', { exact: true }).fill('local-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const pending = page.getByRole('button', { name: 'Signing in…', exact: true });
  await expect(pending).toBeDisabled();
  await expect(pending).toHaveAttribute('aria-busy', 'true');
  await expect(
    page.getByRole('button', { name: 'Forgot your password?', exact: true }),
  ).toBeDisabled();
  completeRequest!();
  await expect(page.getByRole('alert')).toHaveText('Incorrect email, username or password');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Email or username', { exact: true })).toHaveValue('traveler');
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
