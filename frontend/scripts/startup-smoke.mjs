import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const base = process.env.NFI_STARTUP_TEST_URL;
if (!base?.startsWith('http://127.0.0.1:'))
  throw new Error('An isolated local test URL is required');
const marker = await fetch(`${base}/nfi-account-test`).then((response) => response.json());
if (marker.isolated !== true || marker.trading_enabled !== false)
  throw new Error('Refusing startup changes outside the fixture-only integration server');
const afterRestart = process.argv.includes('--after-restart');
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  const trading = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (
      /\/api\/v1\/(?:start|stop|pause|reload_config|forceenter|forceexit)$/.test(
        new URL(request.url()).pathname,
      )
    )
      trading.push(request.url());
  });
  await page.goto(`${base}/login?redirect=/settings`);
  await page.getByLabel('机器人名称', { exact: true }).fill('隔离启动设置测试');
  await page.getByLabel('用户名', { exact: true }).fill('paper');
  await page.getByLabel('密码', { exact: true }).fill('Initial-paper-pass-123');
  await page.getByRole('button', { name: '提交', exact: true }).click();
  const section = page.getByRole('region', { name: '机器人启动', exact: true });
  const toggle = section.getByRole('switch', {
    name: '容器启动／重启后自动启动机器人',
    exact: true,
  });
  await expect(toggle).toHaveAttribute('aria-checked', String(afterRestart));
  await toggle.click();
  await section.getByLabel('当前管理员密码', { exact: true }).fill('Initial-paper-pass-123');
  await section.getByRole('button', { name: '保存启动设置', exact: true }).click();
  if (!afterRestart)
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(section.getByRole('status').filter({ hasText: '启动设置已保存' })).toBeVisible();
  await expect(section.getByLabel('当前管理员密码', { exact: true })).toHaveValue('');
  await page.reload();
  await expect(toggle).toHaveAttribute('aria-checked', String(!afterRestart));
  await mkdir('../artifacts/startup-preview', { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await section.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: `../artifacts/startup-preview/settings-${width}.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
  expect(trading).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'Initial-paper-pass-123',
  );
  console.log(
    afterRestart
      ? 'PASS: actual startup preference survived container restart and can be disabled without trading controls.'
      : 'PASS: actual authenticated startup save, confirmation, persisted reload and desktop/mobile layout; no trading controls.',
  );
} finally {
  await browser.close();
}
