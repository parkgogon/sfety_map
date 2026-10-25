// Rebuild first with npm run build:weather. Requires Playwright Core + Chromium + ffmpeg.
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || '/opt/codex/cua_node/lib/node_modules/playwright-core/index.mjs');
const out = path.resolve(process.env.WEATHER_CAPTURE_DIR || '/workspace/improvement-checks/weather-motion');
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_EXECUTABLE || '/usr/bin/chromium',
  headless: true, args: ['--no-sandbox'], ...(process.env.HTTPS_PROXY ? { proxy: { server: process.env.HTTPS_PROXY, bypass: 'localhost,127.0.0.1' } } : {}) });
const results = [], errors = [], unexpectedRequests = [];
for (const [width, height] of [[1440, 960], [390, 844]]) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    if (['localhost', '127.0.0.1'].includes(url.hostname)) return route.continue();
    unexpectedRequests.push(url.hostname); return route.abort();
  });
  await page.goto(process.env.WEATHER_PREVIEW_URL || 'http://127.0.0.1:8766/preview.html');
  await page.waitForFunction(() => window.weatherPreview);
  // Freeze at matching elapsed times. This clock only exists in the development entry.
  for (let frame = 0; frame < 60; frame++) await page.evaluate(t => window.weatherPreview.seek(t, false), frame / 30);
  for (const layer of ['wind', 'temperature', 'rainfall']) {
    await page.locator(`[data-layer=${layer}]`).click();
    if (layer === 'wind') for (let frame = 0; frame < 60; frame++) await page.evaluate(t => window.weatherPreview.seek(t, false), frame / 30);
    for (const option of (width < 800 ? ['current', 'A', 'B'] : ['all'])) {
      if (option !== 'all') await page.locator(`[data-tab=${option}]`).click();
      await page.evaluate(() => window.weatherPreview.seek(2, false));
      await page.screenshot({ path: path.join(out, `${layer}-${width}-${option}.png`), fullPage: true });
    }
  }
  await page.locator('[data-layer=wind]').click();
  if (width < 800) await page.locator('.mobile-tabs').scrollIntoViewIfNeeded();
  const framesDir = path.join(out, `frames-${width}`); await fs.mkdir(framesDir, { recursive: true });
  for (let frame = 0; frame < 180; frame++) {
    const time = frame / 12;
    if (width < 800) {
      const sectionStart = time < 3 ? 0 : time < 7 ? 3 : time < 11 ? 7 : 11;
      const duration = sectionStart === 0 ? 3 : 4;
      const option = ['current', 'A', 'B'][Math.min(2, Math.floor((time - sectionStart) / duration * 3))];
      await page.locator(`[data-tab=${option}]`).click();
      await page.evaluate(() => document.querySelector('.mobile-tabs').scrollIntoView());
    }
    await page.evaluate(t => window.weatherPreview.seek(t), time);
    await page.screenshot({ path: path.join(framesDir, `${String(frame).padStart(4, '0')}.jpg`), type: 'jpeg', quality: 85 });
    if ([12, 48, 96, 150].includes(frame)) results.push({ width, time, state: await page.evaluate(() => window.weatherPreview.state()) });
  }
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', '12', '-i', path.join(framesDir, '%04d.jpg'),
    '-c:v', 'libx264', '-crf', '21', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path.join(out, `wind-${width}.mp4`)]);
  await page.close();
}
await browser.close();
await fs.writeFile(path.join(out, 'results.json'), JSON.stringify({ scope: 'Synthetic inputs + schematic. Current renderer reused; SDK zoom behavior simulated. Mobile viewport emulation, not a physical device.', results, errors, unexpectedRequests }, null, 2));
console.log(JSON.stringify({ videos: 2, captures: 12, errors, unexpectedRequests }));
if (errors.length || unexpectedRequests.length) process.exitCode = 1;
