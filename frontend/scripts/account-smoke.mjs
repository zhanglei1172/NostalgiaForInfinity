import { chromium, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
const base = process.env.NFI_ACCOUNT_TEST_URL;
if (!base?.startsWith('http://127.0.0.1:'))
  throw new Error('An isolated local test URL is required');
const marker = await fetch(`${base}/nfi-account-test`).then((response) => response.json());
if (marker.isolated !== true || marker.trading_enabled !== false)
  throw new Error('Refusing account mutations outside the fixture-only integration server');
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  reducedMotion: 'reduce',
});
const oldPassword = 'Initial-paper-pass-123';
const newPassword = '中文账户新密码-2026-Strong!';
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
async function signIn(password) {
  await page.getByLabel('机器人名称', { exact: true }).fill('账户测试机器人');
  await page.getByLabel('用户名', { exact: true }).fill('paper');
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '提交', exact: true }).click();
}
try {
  await page.goto(`${base}/login?redirect=/account`);
  if (!process.argv.includes('--after-restart')) {
    await signIn(oldPassword);
    await expect(page.getByRole('heading', { name: '账户与安全', exact: true })).toBeVisible();
    const form = page.locator('form').first();
    await form.getByLabel('当前密码', { exact: true }).fill('incorrect-password');
    await form.getByLabel('新密码', { exact: true }).fill(newPassword);
    await form.getByLabel('确认新密码', { exact: true }).fill(newPassword);
    await form.getByRole('button', { name: '保存密码并重新登录' }).click();
    await expect(page.getByText('当前密码不正确。', { exact: true })).toBeVisible();
    await form.getByLabel('当前密码', { exact: true }).fill(oldPassword);
    await form.getByRole('button', { name: '保存密码并重新登录' }).click();
    await expect(page.getByText('密码已更新，请使用新密码登录。', { exact: true })).toBeVisible();
  }
  await signIn(oldPassword);
  await expect(
    page.getByText('已连接机器人，但登录失败，请检查用户名和密码。', { exact: true }),
  ).toBeVisible();
  await signIn(newPassword);
  await expect(page.getByRole('heading', { name: '账户与安全', exact: true })).toBeVisible();
  await mkdir('../artifacts/account-preview', { recursive: true });
  await page.screenshot({ path: '../artifacts/account-preview/account-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: '../artifacts/account-preview/account-mobile.png',
    fullPage: true,
  });
  const sessions = page.locator('form').last();
  await sessions.getByLabel('当前密码', { exact: true }).fill(newPassword);
  await sessions.getByRole('button', { name: '退出所有设备', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(page.getByText('所有设备的登录已失效，请重新登录。', { exact: true })).toBeVisible();
  await signIn(newPassword);
  await expect(page.getByRole('heading', { name: '账户与安全', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '退出当前设备', exact: true }).click();
  await expect(page.getByText('你已退出当前设备。', { exact: true })).toBeVisible();
  expect(
    await page.evaluate(() => JSON.parse(localStorage.getItem('ftAuthLoginInfo') ?? '{}')),
  ).toEqual({});
  if (errors.length) throw new Error(errors.join('\n'));
  console.log(
    'Real account browser integration passed: password change, Unicode login, old-password rejection, session revocation, desktop/mobile rendering.',
  );
} finally {
  await browser.close();
}
