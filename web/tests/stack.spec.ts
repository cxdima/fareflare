import { expect, test } from '@playwright/test';
import { mock } from './fixtures';

/** Check the served application, including lazy dashboard code, rather than package declarations. */
test('the site runs Angular and Bootstrap without loading a React renderer or external scripts', async ({
  page,
}) => {
  await mock(page);
  const loadedScripts: string[] = [];
  const scriptBodies: Promise<string>[] = [];
  page.on('response', (response) => {
    if (response.request().resourceType() === 'script') {
      loadedScripts.push(response.url());
      scriptBodies.push(response.text());
    }
  });
  const checkRuntime = async () => {
    const markers = await page.evaluate(() => {
      const environment = window as typeof window & {
        React?: unknown;
        ReactOnRails?: unknown;
        __REACT_DEVTOOLS_GLOBAL_HOOK__?: { renderers?: Map<number, unknown> };
      };
      return {
        reactGlobal: environment.React !== undefined || environment.ReactOnRails !== undefined,
        reactDom:
          document.querySelector('[data-reactroot], [data-reactid], div[id*="react-root"]') !==
          null,
        reactProperties: Array.from(document.querySelectorAll('*')).some((node) =>
          Object.getOwnPropertyNames(node).some(
            (key) =>
              key === '_reactRootContainer' ||
              key.startsWith('__reactFiber$') ||
              key.startsWith('__reactContainer$'),
          ),
        ),
        renderers: environment.__REACT_DEVTOOLS_GLOBAL_HOOK__?.renderers?.size ?? 0,
      };
    });
    expect(markers).toEqual({
      reactGlobal: false,
      reactDom: false,
      reactProperties: false,
      renderers: 0,
    });
  };
  await page.goto('/');
  await expect(page.locator('ff-public')).toBeVisible();
  await expect(page.locator('[ng-version]')).toHaveAttribute('ng-version', /^\d+\.\d+\.\d+$/);
  await checkRuntime();
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Your flights', exact: true })).toBeVisible();
  await checkRuntime();
  for (const name of ['API & MCP', 'Account settings']) {
    await page
      .getByRole('navigation', { name: 'Main navigation', exact: true })
      .getByRole('link', { name, exact: true })
      .click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await checkRuntime();
  }
  const bootstrapFont = await page.evaluate(() =>
    getComputedStyle(document.documentElement).getPropertyValue('--bs-body-font-family'),
  );
  expect(bootstrapFont).toContain('Plus Jakarta Sans');
  await page.goto('/docs');
  await expect(
    page.getByRole('heading', { name: 'Fareflare API reference', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.locator('script')).toHaveCount(0);
  await checkRuntime();
  expect(loadedScripts.length).toBeGreaterThan(1);
  expect(loadedScripts.every((url) => new URL(url).origin === 'http://127.0.0.1:8007')).toBe(true);
  for (const body of await Promise.all(scriptBodies)) {
    expect(body).not.toMatch(
      /react\.transitional\.element|react\.element|__REACT_DEVTOOLS_GLOBAL_HOOK__|react-dom/,
    );
  }
});
