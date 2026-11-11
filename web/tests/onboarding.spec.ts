import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { fakePasskeys, flightUrl, mock } from './fixtures';

const axe = async (page: import('@playwright/test').Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze())
    .violations;

test('sign-up explains invalid fields, focuses the first error, and never submits invalid input', async ({
  page,
}) => {
  const submissions: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/auth/')) {
      submissions.push(request.url());
    }
  });
  await page.goto('/register');
  await page.getByLabel('Email', { exact: true }).fill('not an address');
  await page.getByLabel('Password', { exact: true }).fill('too short');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByText('Use at least 15 characters.', { exact: true })).toBeVisible();
  await expect(
    page.getByText('Enter an email address, like name@example.com.', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Email', { exact: true })).toBeFocused();
  await expect(page.getByLabel('Email', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  expect(submissions).toEqual([]);
  expect(await axe(page)).toEqual([]);
});

test('signing up sends the address and opens the workspace, with no code to keep', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/register');
  await expect(page.getByText('Free, with 3 flight monitors. No card needed.')).toBeVisible();
  await page.getByLabel('Email', { exact: true }).fill('  traveler@example.com ');
  await page.getByLabel('Password', { exact: true }).fill('long-local-test-password');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(calls.find((call) => call.path === '/auth/register')!.body).toEqual({
    email: 'traveler@example.com',
    password: 'long-local-test-password',
  });
  await expect(
    page.getByRole('heading', { name: 'Which flight are you watching?', exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/recovery code/i)).toHaveCount(0);
});

test('password visibility is accessible and each sign-in page has its own address', async ({
  page,
}) => {
  await mock(page, false);
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
  await expect(page.getByText('Enter your email address.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Forgot password?', exact: true }).click();
  await expect(page).toHaveURL('/forgot-password');
  await expect(
    page.getByRole('heading', { name: 'Reset your password', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('Password', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Enter your email address.', { exact: true })).toHaveCount(0);
  await page.goBack();
  await expect(page).toHaveURL('/login');
  await expect(page.getByRole('heading', { name: 'Welcome back', exact: true })).toBeVisible();
  // The old recovery address leads to the same page.
  await page.goto('/recover');
  await expect(page).toHaveURL('/forgot-password');
});

test('each sign-in page tells a password manager what its fields are', async ({ page }) => {
  await mock(page, false);
  await page.goto('/login');
  await expect(page).toHaveTitle('Sign in · Fareflare');
  const name = page.getByLabel('Email', { exact: true });
  const password = page.locator('#password');
  // "webauthn" lets 1Password and the browser offer a passkey in the same autofill list.
  await expect(name).toHaveAttribute('autocomplete', 'username webauthn');
  await expect(name).toHaveAttribute('type', 'email');
  await expect(password).toHaveAttribute('autocomplete', 'current-password');
  await expect(password).not.toHaveAttribute('passwordrules', /.*/);

  // What was typed follows the visitor to the page they meant to open.
  await name.fill('Traveler@Example.com');
  await page.getByRole('button', { name: 'Create a free account', exact: true }).click();
  await expect(page).toHaveURL('/register');
  await expect(page).toHaveTitle('Create your account · Fareflare');
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeFocused();
  await expect(name).toHaveValue('Traveler@Example.com');
  await expect(name).toHaveAttribute('autocomplete', 'username');
  await expect(password).toHaveAttribute('autocomplete', 'new-password');
  await expect(password).toHaveAttribute('passwordrules', 'minlength: 15; maxlength: 128;');
  await expect(password).toHaveValue('');
});

test('a forgotten password is reset from an emailed link, with the same answer for any address', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/forgot-password');
  await expect(page).toHaveTitle('Reset your password · Fareflare');
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
  await page.getByRole('button', { name: 'Email me a reset link', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Check your email', exact: true })).toBeFocused();
  await expect(page.getByText('It works once, for 30 minutes.', { exact: false })).toBeVisible();
  expect(calls.find((call) => call.path === '/auth/password-reset')!.body).toEqual({
    email: 'traveler@example.com',
  });
  expect(await axe(page)).toEqual([]);

  // The link carries its token in the fragment, which is removed from the address bar.
  await page.goto('/reset-password#token=reset-token');
  await expect(
    page.getByRole('heading', { name: 'Choose a new password', exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL('/reset-password');
  const saved = page.locator('input[autocomplete="username"]');
  await expect(saved).toHaveValue('traveler@example.com');
  const password = page.getByLabel('New password', { exact: true });
  await expect(password).toHaveAttribute('autocomplete', 'new-password');
  await password.fill('a brand new long password');
  await page.getByRole('button', { name: 'Save and sign in', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(calls.find((call) => call.path === '/auth/password-reset/confirm')!.body).toEqual({
    token: 'reset-token',
    new_password: 'a brand new long password',
  });
});

test('a reset link for an account with two-step sign-in also asks for a code', async ({ page }) => {
  const calls = await mock(page, false);
  await page.goto('/reset-password#token=two-step-token');
  const code = page.getByLabel('Authentication code', { exact: true });
  await expect(code).toHaveAttribute('autocomplete', 'one-time-code');
  await page.getByLabel('New password', { exact: true }).fill('a brand new long password');
  await page.getByRole('button', { name: 'Save and sign in', exact: true }).click();
  await expect(page.getByText('Enter the code.', { exact: true })).toBeVisible();
  await code.fill('123456');
  await page.getByRole('button', { name: 'Save and sign in', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(calls.find((call) => call.path === '/auth/password-reset/confirm')!.body.code).toBe(
    '123456',
  );
});

test('an expired reset link says so and offers a new one', async ({ page }) => {
  await mock(page, false);
  await page.goto('/reset-password#token=expired-token');
  await expect(
    page.getByRole('heading', { name: 'This link has expired', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Send a new link', exact: true }).click();
  await expect(page).toHaveURL('/forgot-password');
});

test('an emailed confirmation link confirms the address', async ({ page }) => {
  const calls = await mock(page, false);
  await page.goto('/confirm-email#token=confirm-token');
  await expect(page.getByRole('heading', { name: 'Email confirmed', exact: true })).toBeVisible();
  await expect(page).toHaveURL('/confirm-email');
  expect(calls.find((call) => call.path === '/auth/email/confirm')!.body).toEqual({
    token: 'confirm-token',
  });
  expect(await axe(page)).toEqual([]);
});

test('two-step sign-in asks for a code a password manager can fill, or a backup code', async ({
  page,
}) => {
  const calls = await mock(page, false);
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
  await page.getByLabel('Password', { exact: true }).fill('a two-step password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const code = page.getByLabel('Authentication code', { exact: true });
  await expect(code).toBeFocused();
  await expect(page).toHaveTitle('Enter your code · Fareflare');
  await expect(code).toHaveAttribute('autocomplete', 'one-time-code');
  await expect(code).toHaveAttribute('inputmode', 'numeric');
  await expect(code).toHaveAttribute('id', 'one-time-code');
  await code.fill('000000');
  await page.getByRole('button', { name: 'Verify and sign in', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('That code is not correct');
  await page.getByRole('button', { name: 'Use a backup code instead', exact: true }).click();
  await expect(page.getByLabel('Backup code', { exact: true })).toHaveAttribute(
    'autocomplete',
    'off',
  );
  await page.getByRole('button', { name: 'Use your authenticator app', exact: true }).click();
  await page.getByLabel('Authentication code', { exact: true }).fill('123456');
  await page.getByRole('button', { name: 'Verify and sign in', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(calls.filter((call) => call.path === '/auth/login/two-factor').at(-1)!.body).toEqual({
    token: 'two-step-token',
    code: '123456',
  });
});

test('a passkey signs in from the button or from the email field autofill', async ({ page }) => {
  await fakePasskeys(page, { autofill: true });
  const calls = await mock(page, false);
  await page.goto('/login');
  // With autofill available, the page asks quietly as soon as it opens; choosing it signs in.
  await expect(page).toHaveURL('/app');
  const sent = calls.find((call) => call.path === '/auth/passkey')!.body;
  expect(sent.challenge_id).toBe('challenge-test');
  expect(sent.credential.rawId).toBe('Y3JlZGVudGlhbA');
  expect(sent.credential.response.userHandle).toBe('dXNlcg');
  expect(
    await page.evaluate(() => (window as unknown as { passkeyCalls: unknown[] }).passkeyCalls),
  ).toEqual([{ kind: 'get', mediation: 'conditional' }]);
});

test('the passkey button opens the prompt itself', async ({ page }) => {
  await fakePasskeys(page);
  const calls = await mock(page, false);
  await page.goto('/login');
  await page.getByRole('button', { name: 'Sign in with a passkey', exact: true }).click();
  await expect(page).toHaveURL('/app');
  expect(calls.filter((call) => call.path === '/auth/passkey')).toHaveLength(1);
});

test('the website sends new visitors to sign-up and returning ones to sign-in', async ({
  page,
}) => {
  await mock(page, false);
  await page.goto('/');
  await page.getByRole('button', { name: 'Start tracking a flight' }).click();
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
      body: JSON.stringify({ detail: 'Incorrect email or password' }),
    });
  });
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill('traveler@example.com');
  await page.getByLabel('Password', { exact: true }).fill('local-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  const pending = page.getByRole('button', { name: 'Signing in…', exact: true });
  await expect(pending).toBeDisabled();
  await expect(pending).toHaveAttribute('aria-busy', 'true');
  await expect(page.getByRole('button', { name: 'Forgot password?', exact: true })).toBeDisabled();
  completeRequest!();
  await expect(page.getByRole('alert')).toHaveText('Incorrect email or password');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
  await expect(page.getByLabel('Email', { exact: true })).toHaveValue('traveler@example.com');
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

test('a flight link pasted on the website is waiting in the add-flight dialog', async ({
  page,
}) => {
  await mock(page);
  await page.goto('/');
  const field = page.getByLabel('Your Google Flights link');
  const note = page.locator('#hero-link-note');
  await expect(note).toContainText('No link yet? Add one after you sign up.');

  // Something that is not a flight link is explained on the spot and goes nowhere.
  await field.fill('https://example.com/travel/flights?tfs=abc');
  await expect(note).toContainText('That is not a Google Flights link.');
  await expect(field).toHaveAttribute('aria-invalid', 'true');
  await page.getByRole('button', { name: 'Start tracking a flight' }).click();
  await expect(page).toHaveURL('/');
  await expect(field).toBeFocused();

  await field.fill(`  ${flightUrl}  `);
  await expect(note).toContainText('Google Flights link recognized.');
  await expect(field).not.toHaveAttribute('aria-invalid', 'true');
  await page.getByRole('button', { name: 'Watch this flight' }).click();

  // Signed in already, so sign-up hands over to the workspace, where the link is waiting.
  await expect(page).toHaveURL(/\/app/);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Google Flights link')).toHaveValue(flightUrl);
  await expect(dialog.locator('.link-note')).toHaveText('Google Flights link recognized.');

  // It is offered once: closing the dialog and coming back does not bring it up again.
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('article').first()).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
