import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  timeout: 30000,
  expect: { timeout: 5000 },
  forbidOnly: !!process.env['CI'],
  retries: process.env['CI'] ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8007',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        channel: process.env['PLAYWRIGHT_CHROME_CHANNEL'] || 'chrome',
      },
    },
  ],
  webServer: [
    {
      command: '../.venv/bin/python tests/serve_portal.py',
      url: 'http://127.0.0.1:8007/v1/config',
      reuseExistingServer: false,
      timeout: 30000,
    },
  ],
});
