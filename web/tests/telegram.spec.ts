import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mock, now } from './fixtures';

const inviteKey = 'fareflare.telegram-invite.user';

async function telegram(page: Page, initial: { enabled?: boolean; connected?: boolean } = {}) {
  const state = { enabled: true, connected: false, reads: 0, links: 0, ...initial };
  await page.route('**/v1/telegram', (route) => {
    const method = route.request().method();
    if (method === 'POST') {
      state.links += 1;
      return route.fulfill({
        json: {
          url: `https://t.me/fareflare_bot?start=ff_example_${state.links}`,
          expires_at: now + 600,
        },
      });
    }
    if (method === 'DELETE') {
      state.connected = false;
      return route.fulfill({ json: { disconnected: true } });
    }
    state.reads += 1;
    return route.fulfill({
      json: { enabled: state.enabled, connected: state.connected, bot_username: 'fareflare_bot' },
    });
  });
  return state;
}

const invitation = (page: Page) => page.getByRole('region', { name: 'Get alerts on your phone' });

test('someone watching a flight is offered Telegram, and the page notices the connection itself', async ({
  page,
}) => {
  await mock(page);
  const state = await telegram(page);
  await page.clock.install();
  await page.goto('/app');
  const offer = invitation(page);
  await expect(offer).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  await offer.getByRole('button', { name: 'Connect Telegram', exact: true }).click();
  const open = offer.getByRole('link', { name: /Open Telegram/ });
  await expect(open).toHaveAttribute('href', 'https://t.me/fareflare_bot?start=ff_example_1');
  await expect(open).toHaveAttribute('target', '_blank');
  await expect(offer.getByRole('listitem')).toHaveCount(2);
  await expect(offer.getByRole('status')).toContainText(
    'Waiting for you to press Start. This page updates by itself.',
  );
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);

  // Nothing changes until Start is pressed in Telegram…
  const reads = state.reads;
  await page.clock.runFor(4100);
  await expect.poll(() => state.reads).toBe(reads + 1);
  await expect(open).toBeVisible();
  // …and once it is, nobody has to come back and press a button.
  state.connected = true;
  await page.clock.runFor(4100);
  await expect(
    offer.getByText('Connected. Price alerts arrive as Telegram messages.'),
  ).toBeVisible();
  await expect(open).toHaveCount(0);
  const settled = state.reads;
  await page.clock.runFor(20000);
  expect(state.reads).toBe(settled);

  await offer.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(offer).toHaveCount(0);
});

test('declining the Telegram offer is remembered, and settings still offers it', async ({
  page,
}) => {
  await mock(page);
  await telegram(page);
  await page.goto('/app');
  await invitation(page).getByRole('button', { name: 'Not now', exact: true }).click();
  await expect(invitation(page)).toHaveCount(0);
  expect(await page.evaluate((key) => localStorage.getItem(key), inviteKey)).toBe('hidden');
  await page.reload();
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(invitation(page)).toHaveCount(0);

  await page.goto('/app#settings?section=connections');
  await expect(page.getByText('Not connected', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect Telegram', exact: true })).toBeVisible();
});

test('the Telegram offer waits for a flight and for Telegram to be available', async ({ page }) => {
  await mock(page);
  const state = await telegram(page, { enabled: false });
  await page.goto('/app');
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(invitation(page)).toHaveCount(0);

  state.enabled = true;
  await page.route(/\/v1\/monitors(?:\?|$)/, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null, active_count: 0 } }),
  );
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Which flight are you watching?' })).toBeVisible();
  await expect(invitation(page)).toHaveCount(0);

  state.connected = true;
  await page.unroute(/\/v1\/monitors(?:\?|$)/);
  await page.reload();
  await expect(page.getByRole('article')).toHaveCount(1);
  await expect(invitation(page)).toHaveCount(0);
});

test('settings shares the connection in progress and can replace or drop it', async ({ page }) => {
  await mock(page);
  const state = await telegram(page);
  await page.clock.install();
  await page.goto('/app');
  await invitation(page).getByRole('button', { name: 'Connect Telegram', exact: true }).click();
  await page.getByRole('link', { name: 'Account settings', exact: true }).click();
  await page
    .getByRole('navigation', { name: 'Settings sections' })
    .getByRole('button', { name: 'Connections', exact: true })
    .click();
  // The link made on the flights page is the one shown here: one connection, two doors.
  const open = page.getByRole('link', { name: /Open Telegram/ });
  await expect(open).toHaveAttribute('href', 'https://t.me/fareflare_bot?start=ff_example_1');
  await page.getByRole('button', { name: 'Create a new link', exact: true }).click();
  await expect(open).toHaveAttribute('href', 'https://t.me/fareflare_bot?start=ff_example_2');

  state.connected = true;
  await page.getByRole('button', { name: 'Check now', exact: true }).click();
  await expect(page.getByText('Connected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Disconnect Telegram', exact: true }).click();
  await expect(page.getByText('Not connected', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect Telegram', exact: true })).toBeVisible();
});

test('a link that is not a Telegram address is refused', async ({ page }) => {
  await mock(page);
  await telegram(page);
  await page.route('**/v1/telegram', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ json: { url: 'https://example.com/steal', expires_at: now + 600 } })
      : route.fallback(),
  );
  await page.goto('/app');
  await invitation(page).getByRole('button', { name: 'Connect Telegram', exact: true }).click();
  await expect(invitation(page).getByRole('alert')).toHaveText(
    'The server returned an invalid Telegram link.',
  );
  await expect(page.getByRole('link', { name: /Open Telegram/ })).toHaveCount(0);
});
