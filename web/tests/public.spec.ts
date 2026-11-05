import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const origin = 'http://127.0.0.1:8007';
const github = 'https://github.com/cxdima/fareflare';

test('landing page has accessible navigation, loaded artwork, and a usable mobile layout', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (entry) => {
    if (/Content Security Policy|Refused to/.test(entry.text())) errors.push(entry.text());
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(
    'Know when your flight price drops',
  );
  await expect(page.locator(`a[href="${github}"]`).first()).toBeVisible();
  await expect(page.locator('main')).toBeVisible();
  await expect(page.locator('[style]')).toHaveCount(0);
  await expect
    .poll(async () =>
      page
        .locator('img')
        .evaluateAll((images) => images.every((image) => image.complete && image.naturalWidth > 0)),
    )
    .toBe(true);
  expect(await page.locator('img').count()).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Below my price', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Below my price', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByText('Your flight is below $220', { exact: true })).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.getByRole('button', { name: 'A new low', exact: true }).click();
  await expect(page.getByText('New low recorded at $191', { exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: 'artifacts/landing-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({ path: 'artifacts/landing-mobile.png', fullPage: true });
  await page.getByRole('link', { name: 'Guides', exact: true }).first().click();
  await expect(page).toHaveURL(origin + '/guides');
  await page.locator('a[href="/guides/reading-flight-price-alerts"]').first().click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'What a flight price alert actually tells you',
  );
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    'href',
    origin + '/guides/reading-flight-price-alerts',
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({ path: 'artifacts/guide-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('public content is readable without JavaScript and uses canonical structured metadata', async ({
  browser,
  request,
}) => {
  const sitemap = await request.get('/sitemap.xml');
  expect(sitemap.status()).toBe(200);
  expect(sitemap.headers()['content-type']).toContain('xml');
  const urls = [...(await sitemap.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map(
    (match) => match[1],
  );
  expect(urls).toContain(origin + '/');
  expect(urls.every((url) => new URL(url).origin === origin)).toBe(true);
  expect(
    urls.some((url) =>
      /\/(app|login|register|recover|auth|v1)(?:\/|$)/.test(new URL(url).pathname),
    ),
  ).toBe(false);
  const articles = urls.filter(
    (url) => new URL(url).pathname.split('/').filter(Boolean).length === 2,
  );
  expect(articles.length).toBeGreaterThanOrEqual(3);

  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  try {
    await page.goto(origin);
    await expect(page.getByRole('heading', { level: 1 })).toContainText(
      'Know when your flight price drops',
    );
    const titles = new Set<string>();
    for (const url of articles) {
      const response = await page.goto(url);
      expect(response?.status()).toBe(200);
      await expect(page.locator('h1')).toHaveCount(1);
      await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', url);
      const description = await page.locator('meta[name="description"]').getAttribute('content');
      expect(description?.length).toBeGreaterThan(40);
      await expect(page.locator('meta[property="og:url"]')).toHaveAttribute('content', url);
      const socialImage = await page.locator('meta[property="og:image"]').getAttribute('content');
      expect(socialImage).toBeTruthy();
      expect((await request.get(socialImage!)).status()).toBe(200);
      const data = (
        await page.locator('script[type="application/ld+json"]').allTextContents()
      ).flatMap((text) => {
        const value = JSON.parse(text);
        return value['@graph'] ?? [value];
      });
      const article = data.find((value) => [value['@type']].flat().includes('BlogPosting'));
      expect(article).toBeTruthy();
      expect(article.headline).toBe(await page.locator('h1').innerText());
      expect(article.author).toBeTruthy();
      expect(Number.isNaN(Date.parse(article.datePublished))).toBe(false);
      expect((await page.locator('article').innerText()).length).toBeGreaterThan(500);
      await expect(page.locator('[style]')).toHaveCount(0);
      titles.add(await page.title());
    }
    expect(titles.size).toBe(articles.length);
  } finally {
    await context.close();
  }
});

test('private pages stay out of indexing and invalid public routes return HTTP 404', async ({
  request,
}) => {
  const robots = await request.get('/robots.txt');
  expect(robots.status()).toBe(200);
  expect(await robots.text()).toContain(`Sitemap: ${origin}/sitemap.xml`);
  for (const path of ['/app', '/login', '/register', '/recover']) {
    const response = await request.get(path);
    expect(response.status()).toBe(200);
    expect(response.headers()['x-robots-tag']).toContain('noindex');
    expect(response.headers()['content-security-policy']).not.toContain("'unsafe-inline'");
    expect(response.headers()['content-security-policy']).not.toContain("'unsafe-eval'");
  }
  const missing = await request.get('/this-page-does-not-exist');
  expect(missing.status()).toBe(404);
  expect((await missing.text()).toLowerCase()).toContain('not found');
});
