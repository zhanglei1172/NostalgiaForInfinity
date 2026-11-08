import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const base = process.env.NFI_LIVE_TEST_URL ?? 'http://127.0.0.1:18081';
const url = new URL(base);
if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1')
  throw new Error('A local live-management URL is required');
const status = await fetch(`${base}/api/v1/live/setup-status`).then((response) => response.json());
if (status.required !== true) throw new Error('This check expects an unclaimed administrator');

const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  const page = await browser.newPage({ reducedMotion: 'reduce' });
  const errors = [];
  const writes = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/v1/**', (route) => {
    if (route.request().method() === 'GET') return route.continue();
    writes.push(route.request().method());
    return route.abort();
  });
  await mkdir('../artifacts/live-preview', { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${base}/login`);
    await expect(page.getByRole('heading', { name: '创建管理员账号', exact: true })).toBeVisible();
    await expect(page.getByLabel('管理员用户名', { exact: true })).toBeVisible();
    await expect(page.getByLabel('管理员密码', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '创建账号并登录', exact: true })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `../artifacts/live-preview/setup-${width}.png`, fullPage: true });
  }
  expect(errors).toEqual([]);
  expect(writes).toEqual([]);
  const unchanged = await fetch(`${base}/api/v1/live/setup-status`).then((response) =>
    response.json(),
  );
  expect(unchanged.required).toBe(true);
  console.log(
    'Live setup passed on desktop/mobile; no account created, settings saved or trading controls called.',
  );
} finally {
  await browser.close();
}
