// Read-only local deployment check. Never saves a draft, changes an account or starts trading.
import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const base = process.env.NFI_LIVE_TEST_URL;
const container = process.env.NFI_LIVE_TEST_CONTAINER;
if (!base || !/^http:\/\/127\.0\.0\.1:\d+$/.test(base) || !container)
  throw new Error('Specify the local live URL and its container explicitly');
const script = `
import json
from pathlib import Path
from freqtrade.rpc.api_server.api_auth import create_token
account=json.loads(Path('/freqtrade/user_data/.nfi-account.json').read_text())
data={'identity':{'u':account['username']}}
print(json.dumps({'username':account['username'],'accessToken':create_token(data,account['jwt_secret']),
 'refreshToken':create_token(data,account['jwt_secret'],'refresh')}))
`;
// Signing data and tokens stay in this private pipe and the temporary browser context.
const credentials = JSON.parse(
  execFileSync('docker', ['exec', container, 'python', '-c', script], { encoding: 'utf8' }),
);
async function read(path) {
  const response = await fetch(base + '/api/v1/' + path, {
    headers: { Authorization: 'Bearer ' + credentials.accessToken },
  });
  if (!response.ok) throw new Error(`Read-only check failed for ${path}: HTTP ${response.status}`);
  return response.json();
}
const before = await read('live-recipe');
const config = await read('show_config');
expect(config.nfi_live_management).toBe(true);
expect(before.exchange).toBe('okx');
expect((await read('research/info')).exchange).toBe('okx');
expect((await read('research/strategies')).strategies).toContain('NostalgiaForInfinityX8');
expect((await fetch(base + '/api/v1/live-recipe')).status).toBe(401);
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: 'reduce',
  });
  const errors = [];
  const mutations = [];
  page.on('pageerror', () => errors.push(true));
  await page.route('**/api/v1/**', (route) => {
    if (route.request().method() !== 'GET' || route.request().url().includes('/backtest/abort')) {
      mutations.push(new URL(route.request().url()).pathname);
      return route.abort();
    }
    return route.continue();
  });
  await page.addInitScript(
    ({ base, credentials }) => {
      localStorage.setItem(
        'ftAuthLoginInfo',
        JSON.stringify({
          liveRecipeCheck: {
            ...credentials,
            botName: 'NFI 实盘检查',
            apiUrl: base,
            autoRefresh: true,
          },
        }),
      );
    },
    { base, credentials },
  );
  await page.goto(base + '/recipes');
  await expect(
    page.getByRole('heading', { name: '实盘配置与模拟盘对比', exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(page.getByLabel('当前管理员密码', { exact: true })).toHaveValue('');
  await mkdir('../artifacts/live-recipe-preview', { recursive: true });
  await page.screenshot({ path: '../artifacts/live-recipe-preview/real-live-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('heading', { name: '实盘配置与模拟盘对比', exact: true })
    .scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/live-recipe-preview/real-live-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(base + '/strategies');
  await expect(
    page.getByRole('heading', { name: 'NostalgiaForInfinityX8', exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await page.goto(base + '/backtest');
  await expect(page.getByRole('button', { name: '2. 开始回测', exact: true })).toBeVisible({
    timeout: 30000,
  });
  await expect(
    page.getByText('研究使用模拟盘已保存配方与研究策略代码，不会修改或启动实盘交易。', {
      exact: true,
    }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  expect(mutations).toEqual([]);
  const after = await read('live-recipe');
  expect(after.saved).toEqual(before.saved);
  expect(after.live_revision).toBe(before.live_revision);
  expect(after.configured).toBe(before.configured);
  console.log(
    'Live read-only smoke passed: authenticated recipe comparison, shared research gateway, strategy library, backtesting, desktop and mobile. No configuration or trading changes.',
  );
} finally {
  await browser.close();
}
