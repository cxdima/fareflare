// Renders the README figures from the HTML in ./src to WebP files in this folder.
//   node docs/readme/render.mjs        (needs `npm --prefix web ci` for Playwright)
// The browser encodes WebP itself, so no image library is needed.
import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const here = new URL('.', import.meta.url);
const { chromium } = createRequire(new URL('../../web/package.json', import.meta.url))('@playwright/test');

const figures = [
  ['hero', 'hero.html'],
  ['screens', 'screens.html'],
  ['security', 'security.html'],
  ['architecture', 'architecture.html'],
  ['banner-how', 'banner.html?n=01&title=How%20it&turn=works&art=how'],
  ['banner-alerts', 'banner.html?n=02&title=Alerts%20where&turn=you%20look&art=alerts'],
  ['banner-developers', 'banner.html?n=03&title=Build&turn=on%20it&art=developers'],
  ['banner-run', 'banner.html?n=04&title=Run%20it&turn=yourself&art=selfhost'],
];

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 1280, height: 800 } });
for (const [name, source] of figures) {
  await page.goto(new URL('src/' + source, here).href);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState('networkidle');
  const png = await page.locator('#figure').screenshot({ omitBackground: true });
  const webp = await page.evaluate(async (base64) => {
    const bitmap = await createImageBitmap(await (await fetch('data:image/png;base64,' + base64)).blob());
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    canvas.getContext('2d').drawImage(bitmap, 0, 0);
    const blob = await canvas.convertToBlob({ type: 'image/webp', quality: 0.9 });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }, png.toString('base64'));
  const target = fileURLToPath(new URL(name + '.webp', here));
  await writeFile(target, Buffer.from(webp, 'base64'));
  console.log(name, Math.round(Buffer.from(webp, 'base64').length / 1024) + ' KiB');
}
await browser.close();
