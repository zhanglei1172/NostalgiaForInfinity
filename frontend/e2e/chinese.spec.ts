import { expect, test } from '@playwright/test';
import { mockBot, login } from './helpers';

test('defaults to Chinese, switches to English, and retains language after reload', async ({
  page,
}, testInfo) => {
  await mockBot(page);
  await page.goto('/login');
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
  await expect(page.getByLabel('用户名', { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('login-zh.png'), fullPage: true });
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await page.reload();
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Interface language' }).click();
  await page.getByRole('option', { name: '简体中文', exact: true }).click();
  await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
});

test('renders Chinese trade screens and cancels a translated stop confirmation', async ({
  page,
}, testInfo) => {
  const requests = await mockBot(page);
  await login(page);
  await expect(page.getByText('已平仓交易', { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole('columnheader', { name: '交易对', exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('trading-zh.png'), fullPage: true });
  await page.getByTitle('停止交易，同时停止管理已有持仓。', { exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('停止机器人', { exact: true })).toBeVisible();
  await expect(
    dialog.getByText('确定停止机器人的交易循环吗？停止后将不再管理已有持仓。'),
  ).toBeVisible();
  await dialog.getByRole('button', { name: '取消', exact: true }).click();
  expect(requests.filter((request) => request.endpoint === 'stop')).toEqual([]);
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(page.getByRole('columnheader', { name: 'Pair', exact: true }).first()).toBeVisible();
  await page.getByTitle('Stop Trading - Also stops handling open trades.', { exact: true }).click();
  await expect(
    page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }),
  ).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('combobox', { name: 'Interface language' }).click();
  await page.getByRole('option', { name: '简体中文', exact: true }).click();
  await page.goto('/logs');
  await expect(page.getByRole('button', { name: '刷新日志', exact: true })).toBeVisible();
});

test('Chinese order controls preserve API values and custom entry tags', async ({ page }) => {
  const requests = await mockBot(page);
  await login(page);
  await page
    .getByTitle('强制开仓：立即以指定价格或默认价格开仓，之后由策略管理退出。', { exact: true })
    .click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('交易对', { exact: true }).fill('BTC/USDT');
  await dialog.getByText('市价', { exact: true }).click();
  await dialog.locator('#enterTag-input').fill('我的测试标签');
  await dialog.getByRole('button', { name: '开仓', exact: true }).click();
  await expect
    .poll(() => requests.find((request) => request.endpoint === 'forcebuy')?.body)
    .toEqual({
      pair: 'BTC/USDT',
      ordertype: 'market',
      entry_tag: '我的测试标签',
    });
});

test('language selection is available on a mobile login screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBot(page);
  await page.goto('/login');
  await expect(page.getByRole('combobox', { name: '界面语言' })).toBeInViewport();
  await expect(page.getByLabel('用户名', { exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});
