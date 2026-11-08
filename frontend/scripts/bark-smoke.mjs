import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const base = process.env.NFI_BARK_TEST_URL;
if (!base?.startsWith('http://127.0.0.1:'))
  throw new Error('Specify an isolated local fixture URL');
const marker = await fetch(`${base}/nfi-account-test`).then((r) => r.json());
if (marker.isolated !== true || marker.trading_enabled !== false)
  throw new Error('Refusing to modify notifications outside the fixture-only integration server');
const status = () => fetch(`${base}/fixture-bark/status`).then((r) => r.json());
const change = (body) =>
  fetch(`${base}/fixture-bark/sample`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
const count = async (name) =>
  (await status()).receipts.filter((r) => r.title.includes(name)).length;
if (process.argv.includes('--after-restart')) {
  const before = await status();
  expect(await count('收益达标')).toBe(1);
  // Wait for a fresh background sample to prove that the restarted monitor did evaluate the threshold.
  await expect
    .poll(async () => (await status()).runtime.last_checked_at, { timeout: 10000 })
    .not.toBe(before.runtime.last_checked_at);
  expect(await count('收益达标')).toBe(1);
  await change({ roi_pct: 4 });
  await expect.poll(async () => (await status()).runtime.roi_pct).toBe(4);
  await change({ roi_pct: 6, clock_offset: 600 });
  await expect.poll(() => count('收益达标')).toBe(2);
  await change({ roi_pct: -3 });
  await expect.poll(() => count('亏损预警')).toBe(1);
  console.log(
    'PASS: persisted Bark deduplication after restart, threshold rearming and loss delivery with the browser closed.',
  );
  process.exit(0);
}
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
      /\/api\/v1\/(start|stop|pause|reload_config|forceenter|forceexit)$/.test(
        new URL(request.url()).pathname,
      )
    )
      trading.push(request.url());
  });
  await page.goto(`${base}/login?redirect=/settings`);
  await page.getByLabel('机器人名称', { exact: true }).fill('隔离 Bark 测试');
  await page.getByLabel('用户名', { exact: true }).fill('paper');
  await page.getByLabel('密码', { exact: true }).fill('Initial-paper-pass-123');
  await page.getByRole('button', { name: '提交', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Bark 通知', exact: true });
  await expect(panel).toBeVisible();
  await panel.getByRole('switch', { name: '开启 Bark 通知', exact: true }).click();
  await panel
    .getByLabel('Bark 推送地址', { exact: true })
    .fill('http://127.0.0.1:8080/fixture-bark/fixture-device-key');
  await panel
    .getByRole('spinbutton', { name: '同类事件通知冷却时间（分钟）', exact: true })
    .fill('5');
  const password = panel.getByLabel('管理员密码（Bark 设置验证）', { exact: true });
  await password.fill('Initial-paper-pass-123');
  await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Bark 通知设置已保存');
  await password.fill('Initial-paper-pass-123');
  await panel.getByRole('button', { name: '发送 Bark 测试通知', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('Bark 已接收测试通知');
  await expect.poll(() => count('测试通知')).toBe(1);
  await mkdir('../artifacts/bark-preview', { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await panel.screenshot({ path: `../artifacts/bark-preview/actual-${width}.png` });
  }
  expect(errors).toEqual([]);
  expect(trading).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
    /fixture-device-key|Initial-paper-pass-123/,
  );
} finally {
  await browser.close();
}
await change({ roi_pct: 6 });
await expect.poll(() => count('收益达标'), { timeout: 10000 }).toBe(1);
console.log(
  'PASS: real authenticated Web save, local Bark POST acceptance, desktop/mobile layout and threshold delivery after closing the browser.',
);
