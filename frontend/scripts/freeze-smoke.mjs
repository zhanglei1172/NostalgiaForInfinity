import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const base = process.env.NFI_AUTH_TEST_URL;
if (!base?.startsWith('http://127.0.0.1:'))
  throw new Error('Specify an isolated local auth fixture URL');
const marker = await fetch(base + '/nfi-auth-test').then((r) => r.json());
if (!marker.isolated || marker.trading_enabled !== false)
  throw new Error('Refusing to test freezes against a trading deployment');
const password = 'Initial-paper-pass-123';
const header = { Authorization: 'Basic ' + Buffer.from('paper:' + password).toString('base64') };
if (process.argv.includes('--after-restart')) {
  expect(marker.retry_after).toBeGreaterThan(0);
  const blocked = await fetch(base + '/api/v1/token/login', { method: 'POST', headers: header });
  expect(blocked.status).toBe(429);
  expect(Number(blocked.headers.get('Retry-After'))).toBeGreaterThan(0);
  await fetch(base + '/fixture-auth/advance', { method: 'POST' });
}
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const controls = [];
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (
      /\/api\/v1\/(start|stop|pause|reload_config|forceenter|forceexit)$/.test(
        new URL(request.url()).pathname,
      )
    )
      controls.push(request.url());
  });
  await page.goto(base + '/login?redirect=/settings');
  await page.getByLabel('机器人名称', { exact: true }).fill('隔离密码冻结验证');
  await page.getByLabel('用户名', { exact: true }).fill('paper');
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '提交', exact: true }).click();
  await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible();
  if (process.argv.includes('--after-restart')) {
    console.log(
      'PASS: the actual auth freeze survived container restart, rejected a correct password, and expired without changing credentials.',
    );
  } else {
    const panel = page.getByRole('region', { name: 'Bark 通知', exact: true });
    await panel.getByRole('spinbutton', { name: '收益率阈值（%）', exact: true }).fill('6');
    for (let index = 0; index < 5; index++) {
      await panel
        .getByLabel('管理员密码（Bark 设置验证）', { exact: true })
        .fill('wrong-fixture-password');
      await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
      if (index < 4) await expect(panel.getByRole('alert')).toContainText('当前密码不正确');
    }
    await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toBeVisible();
    await expect(panel.getByRole('button', { name: '保存 Bark 设置', exact: true })).toBeDisabled();
    const blocked = await page.request.post(base + '/api/v1/token/login', { headers: header });
    expect(blocked.status()).toBe(429);
    await page.reload();
    await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toBeVisible();
    await mkdir('../artifacts/auth-freeze-preview', { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page
        .getByRole('alert')
        .filter({ hasText: '密码验证已暂时冻结' })
        .scrollIntoViewIfNeeded();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({ path: `../artifacts/auth-freeze-preview/frozen-${width}.png` });
    }
    console.log(
      'PASS: fifth incorrect settings password freezes login and settings, persisted JWT sessions still work, and the real Chinese UI restores its countdown after reload.',
    );
  }
  expect(controls).toEqual([]);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
    /Initial-paper-pass-123|wrong-fixture-password/,
  );
} finally {
  await browser.close();
}
