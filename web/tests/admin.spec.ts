import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock, mockAdmin } from './fixtures';

const alice = 'acct_' + 'a'.repeat(32);
const axe = async (page: Page) =>
  (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze())
    .violations;
const tabs = (page: Page) => page.getByRole('navigation', { name: 'Admin sections' });

test('only an admin sees the admin page in the navigation', async ({ page }) => {
  await mock(page);
  await page.goto('/app#admin');
  const nav = page.getByRole('navigation', { name: 'Main navigation' });
  await expect(nav.getByRole('link', { name: 'Flight monitors' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0);
  // Asking for the admin page without the role shows the flights instead.
  await expect(page.getByRole('heading', { name: 'Your flights', level: 1 })).toBeVisible();

  await mockAdmin(page);
  await page.reload();
  await nav.getByRole('link', { name: 'Admin' }).click();
  await expect(page.getByRole('heading', { name: 'Admin', level: 1 })).toBeVisible();
  await expect(page).toHaveURL(/#admin$/);
  await expect(page.getByText(/Admin access until/)).toBeVisible();
  // The workspace Refresh reloads flights, which are not on this page.
  await expect(page.getByRole('button', { name: 'Refresh dashboard' })).toHaveCount(0);
});

test('the panel asks for a second factor, then for a fresh sign-in', async ({ page }) => {
  await mock(page);
  await mockAdmin(page, { gate: 'mfa' });
  await page.goto('/app#admin');
  await expect(page.getByRole('heading', { name: 'Turn on two-step sign-in first' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open security settings' })).toHaveAttribute(
    'href',
    '/app#settings?section=security',
  );
  await expect(tabs(page)).toHaveCount(0);
  expect(await axe(page)).toEqual([]);

  await page.unrouteAll();
  await mock(page);
  const calls = await mockAdmin(page, { gate: 'reauth' });
  await page.reload();
  await page.getByRole('button', { name: 'Sign in again' }).click();
  await expect(page).toHaveURL(/\/login#admin$/);
  expect(
    calls.filter((call) => call.path.startsWith('/v1/admin/') && call.path !== '/v1/admin/gate'),
  ).toEqual([]);
});

test('the overview shows people, flights, checks, protection, email and the service', async ({
  page,
}) => {
  await mock(page);
  await mockAdmin(page);
  await page.goto('/app#admin');
  await expect(page.getByRole('heading', { name: '29 accounts, 6 new this week' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '6 flights watched' })).toBeVisible();
  await expect(page.getByText('5 of 20 shared collection slots in use.')).toBeVisible();
  await expect(page.getByRole('list', { name: '5 of 20 slots used' }).locator('li')).toHaveCount(
    20,
  );
  await expect(page.getByText('1 blocked after repeated failures.')).toBeVisible();
  await expect(page.locator('.hour-bars li')).toHaveCount(24);
  await expect(page.locator('.signup-bars li')).toHaveCount(30);
  await expect(page.getByRole('heading', { name: 'How accounts are protected' })).toBeVisible();
  await expect(page.locator('.budget-full')).toHaveCount(1); // Notices used up this hour.
  expect(await axe(page)).toEqual([]);
  await page.getByRole('button', { name: 'See everyone' }).click();
  await expect(tabs(page).getByRole('button', { name: 'Users' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page).toHaveURL(/#admin\?tab=users$/);
});

test('accounts can be found and opened, and Back returns to the list', async ({ page }) => {
  await mock(page);
  const calls = await mockAdmin(page);
  await page.goto('/app#admin?tab=users');
  const table = page.getByRole('table', { name: 'Accounts' });
  await expect(table.getByRole('row')).toHaveCount(3);
  await page.getByLabel('Find an account').fill('bob');
  await expect(table.getByRole('row')).toHaveCount(2);
  expect(calls.some((call) => call.path === '/v1/admin/users')).toBe(true);
  await page.getByLabel('Find an account').fill('');
  await expect(table.getByRole('row')).toHaveCount(3);
  expect(await axe(page)).toEqual([]);

  await table.getByRole('link', { name: 'alice@example.com' }).click();
  await expect(page).toHaveURL(new RegExp(`#admin\\?tab=users&user=${alice}$`));
  await expect(page.getByRole('heading', { name: 'alice@example.com' })).toBeVisible();
  await expect(page.getByRole('table', { name: "This account's flights" })).toContainText(
    'DEN → DFW',
  );
  await expect(page.getByText('Spreadsheet sync')).toBeVisible();
  await expect(page.getByText('hooks.example.com')).toBeVisible();
  await expect(page.getByText('Verified', { exact: true })).toHaveCount(0);
  expect(await axe(page)).toEqual([]);
  await page.goBack();
  await expect(page.getByRole('table', { name: 'Accounts' })).toBeVisible();
});

test('account actions say what they do, need a reason where it matters, and are recorded', async ({
  page,
}) => {
  await mock(page);
  const calls = await mockAdmin(page);
  await page.goto(`/app#admin?tab=users&user=${alice}`);
  await page.getByRole('button', { name: 'Suspend', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Their flights are kept');
  const confirm = dialog.getByRole('button', { name: 'Suspend account' });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel('Reason').fill('Card testing');
  await confirm.click();
  await expect(
    page.getByRole('status').filter({ hasText: 'Suspended the account.' }),
  ).toBeVisible();
  const suspend = calls.find((call) => call.path.endsWith('/suspend'))!;
  expect(suspend.body).toEqual({ reason: 'Card testing' });
  expect(suspend.csrf).toBe('csrf-test');
  await expect(page.getByRole('heading', { name: 'Reactivate' })).toBeVisible();
  await expect(page.locator('.audit-list')).toContainText('“Card testing”');

  await page.getByRole('button', { name: 'Reactivate', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Reactivate account' }).click();
  await expect(page.getByRole('heading', { name: 'Suspend' })).toBeVisible();

  await page.getByRole('button', { name: 'Issue', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Issue temporary password' }).click();
  const issued = page.getByRole('dialog', { name: 'Temporary password' });
  await expect(issued.locator('code')).toHaveText('Tq9-x2Lm4Zp8');
  expect(await axe(page)).toEqual([]);
  await issued.getByRole('button', { name: 'Done' }).click();
  await expect(page.getByText('Tq9-x2Lm4Zp8')).toHaveCount(0);

  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  const deletion = page.getByRole('dialog');
  const remove = deletion.getByRole('button', { name: 'Delete account' });
  await deletion.getByLabel('Reason').fill('Asked to be removed');
  await expect(remove).toBeDisabled();
  await deletion.getByLabel(/to confirm/).fill('bob@example.com');
  await remove.click();
  await expect(deletion).toContainText("Type the account's email address to confirm.");
  await deletion.getByLabel(/to confirm/).fill('alice@example.com');
  await remove.click();
  await expect(page.getByText('Deleted the account.')).toBeVisible();
  const deleted = calls.find(
    (call) => call.method === 'DELETE' && call.body.confirm === 'alice@example.com',
  );
  expect(deleted?.body).toEqual({ confirm: 'alice@example.com', reason: 'Asked to be removed' });
});

test('a flight is paused at once and stopped after a confirmation', async ({ page }) => {
  await mock(page);
  const calls = await mockAdmin(page);
  await page.goto(`/app#admin?tab=users&user=${alice}`);
  await page.getByRole('button', { name: 'Pause DEN → DFW' }).click();
  await expect(page.getByText('DEN → DFW paused.')).toBeVisible();
  await page.getByRole('button', { name: 'Stop DEN → DFW' }).click();
  await page.getByRole('dialog').getByLabel('Reason (optional)').fill('Duplicate');
  await page.getByRole('dialog').getByRole('button', { name: 'Stop flight' }).click();
  await expect(page.getByText('DEN → DFW stopped.')).toBeVisible();
  const patches = calls.filter((call) => call.method === 'PATCH').map((call) => call.body);
  expect(patches).toEqual([
    { status: 'paused', reason: '' },
    { status: 'cancelled', reason: 'Duplicate' },
  ]);
});

test('flights, activity and the switches', async ({ page }) => {
  await mock(page);
  const calls = await mockAdmin(page);
  await page.goto('/app#admin?tab=flights');
  const flights = page.getByRole('table', { name: 'Flights the service checks' });
  await expect(flights).toContainText('DEN → DFW');
  await expect(flights).toContainText('Checking');
  expect(await axe(page)).toEqual([]);
  await flights.getByRole('link', { name: 'bob@example.com' }).click();
  await expect(page.getByRole('heading', { name: 'bob@example.com' })).toBeVisible();

  await tabs(page).getByRole('button', { name: 'Activity' }).click();
  const activity = page.getByRole('table', { name: 'Admin activity, newest first' });
  await expect(activity).toContainText('Stopped a flight');
  await expect(activity).toContainText('DEN → DFW · “Duplicate”');
  await expect(activity).toContainText('The whole service');
  expect(await axe(page)).toEqual([]);

  await tabs(page).getByRole('button', { name: 'Controls' }).click();
  const checks = page.getByRole('switch', { name: 'Pause every price check' });
  await expect(checks).not.toBeChecked();
  await checks.check();
  await expect(page.getByRole('status')).toContainText('Price checks are paused for every flight.');
  expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ collection_paused: true });
  await expect(page.getByText('The panel cannot make or remove an admin.')).toBeVisible();
  expect(await axe(page)).toEqual([]);
});

test('a temporary password must be replaced before anything else opens', async ({ page }) => {
  await mock(page);
  const calls = await mockAdmin(page, { mustChange: true });
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Choose your password' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toHaveCount(0);
  await expect(page.getByText('Next, you will turn on two-step sign-in')).toBeVisible();
  await expect(page.getByLabel('New password')).toHaveAttribute('autocomplete', 'new-password');
  expect(await axe(page)).toEqual([]);
  await page.getByLabel('Temporary password').fill('124');
  await page.getByLabel('New password').fill('my own long passphrase');
  await page.getByRole('button', { name: 'Save password' }).click();
  await expect(page.getByRole('alert')).toContainText('That password is not correct');
  await page.getByLabel('Temporary password').fill('123');
  await page.getByRole('button', { name: 'Save password' }).click();
  // An admin goes straight on to the second factor the panel needs.
  await expect(page).toHaveURL(/#settings\?section=security$/);
  await expect(page.getByRole('heading', { name: 'Account settings', level: 1 })).toBeVisible();
  expect(calls.filter((call) => call.path === '/auth/password').at(-1)?.body).toEqual({
    current_password: '123',
    new_password: 'my own long passphrase',
  });
});

test('on a phone the admin pages fit the screen and the dock gains the admin item', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 720 });
  await mock(page);
  await mockAdmin(page);
  for (const address of [
    '/app#admin',
    '/app#admin?tab=users',
    `/app#admin?tab=users&user=${alice}`,
    '/app#admin?tab=flights',
    '/app#admin?tab=activity',
    '/app#admin?tab=controls',
  ]) {
    await page.goto(address);
    await expect(page.locator('#admin-content')).toBeVisible();
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    expect(overflow, address).toBeLessThanOrEqual(0);
  }
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link'),
  ).toHaveCount(6);
});
