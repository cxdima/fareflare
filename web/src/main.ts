import { bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/app';
import { appConfig } from './app/app.config';

bootstrapApplication(App, appConfig).catch(() => {
  const root = document.querySelector('app-root');
  if (root && !root.textContent?.trim())
    root.textContent = 'Fareflare could not start. Please reload this page.';
});
