// Read-only checks for an administrator's local Compose deployment. No orders or account changes.
import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';
import { backtestDrawdown } from '../src/utils/backtestDrawdown.ts';

const base = process.env.NFI_RESEARCH_TEST_URL;
const container = process.env.NFI_RESEARCH_TEST_CONTAINER;
if (!base?.startsWith('http://127.0.0.1:') || !container)
  throw new Error('Specify the local research URL and Compose bot container explicitly');
const script = `
import json,os
from nfi_account.credentials import AccountManager
from freqtrade.rpc.api_server.api_auth import create_token
api={'username':os.environ['FREQTRADE__API_SERVER__USERNAME'],'jwt_secret_key':os.environ['FREQTRADE__API_SERVER__JWT_SECRET_KEY']}
AccountManager({'api_server':api,'user_data_dir':'/freqtrade/user_data'})
data={'identity':{'u':api['username']}}
print(json.dumps({'username':api['username'],'accessToken':create_token(data,api['jwt_secret_key']),'refreshToken':create_token(data,api['jwt_secret_key'],'refresh')}))
`;
// Credentials stay in a private pipe and this temporary browser context; never print them.
const credentials = JSON.parse(
  execFileSync('docker', ['exec', container, 'python', '-c', script], { encoding: 'utf8' }),
);
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  reducedMotion: 'reduce',
});
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
await page.addInitScript(
  ({ base, credentials }) => {
    localStorage.setItem(
      'ftAuthLoginInfo',
      JSON.stringify({
        researchCheck: { ...credentials, botName: 'NFI 模拟盘', apiUrl: base, autoRefresh: true },
      }),
    );
  },
  { base, credentials },
);
try {
  await page.goto(base + '/strategies');
  await expect(
    page.getByRole('heading', { name: 'NostalgiaForInfinityX8', exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page.getByRole('link', { name: '使用此策略回测', exact: true }).click();
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '已保存的回测结果', exact: true }).click();
  const savedResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/research/backtest/history/result?') && response.status() === 200,
  );
  const walletResponse = page.waitForResponse(
    (response) =>
      response.url().includes('/research/backtest/history/') &&
      response.url().endsWith('/wallet') &&
      response.status() === 200,
  );
  await page.getByRole('option').first().click();
  const saved = await (await savedResponse).json();
  const savedResult = Object.values(saved.backtest_result.strategy)[0];
  const wallet = await (await walletResponse).json();
  const drawdown = backtestDrawdown(savedResult, wallet);
  expect(drawdown.source).toBe('wallet');
  expect(drawdown.maxRatio).toBeCloseTo(savedResult.wallet_stats.max_relative_drawdown, 8);
  expect(drawdown.maxAmount).toBeCloseTo(savedResult.wallet_stats.max_drawdown_abs, 6);
  const risk = page.getByRole('region', { name: '回撤与修复', exact: true });
  await expect(risk.getByText('计算口径: 钱包估值采样', { exact: true })).toBeVisible();
  await expect(
    risk.getByText((drawdown.maxRatio * 100).toFixed(2) + '%', { exact: true }),
  ).toBeVisible();
  if (drawdown.maximum?.recovered) {
    const recoveryDate =
      new Date(drawdown.maximum.recovered).toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
    await expect(risk.getByText(recoveryDate, { exact: true })).toBeVisible();
  }
  await mkdir('../artifacts/drawdown-preview', { recursive: true });
  await risk.getByRole('heading').evaluate((element) => element.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: '../artifacts/drawdown-preview/real-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await risk.getByRole('heading').evaluate((element) => element.scrollIntoView({ block: 'start' }));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/drawdown-preview/real-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await expect(page.getByRole('heading', { name: '每月回测收益', exact: true })).toBeVisible({
    timeout: 30000,
  });
  expect(await page.locator('.monthly-table tbody tr').count()).toBeGreaterThan(0);
  const table = page.locator('.monthly-table');
  await expect(table).toContainText(savedResult.backtest_start.slice(0, 7));
  const netProfit = new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(savedResult.profit_total_abs);
  await expect(
    page.getByText(`${netProfit} ${savedResult.stake_currency}`, { exact: true }),
  ).toBeVisible();
  await mkdir('../artifacts/research-preview', { recursive: true });
  await page.getByRole('heading', { name: '每月回测收益', exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: '../artifacts/research-preview/monthly-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.monthly-table tbody tr').last().scrollIntoViewIfNeeded();
  await expect(page.locator('.monthly-table tbody tr').last()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/research-preview/monthly-mobile.png' });
  if (errors.length)
    throw new Error('Browser errors occurred during the live read-only smoke check');
  console.log(
    'Live research smoke passed: strategy discovery, authenticated gateway, saved monthly results, wallet drawdown and recovery, desktop and mobile.',
  );
} finally {
  await browser.close();
}
