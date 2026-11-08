// Read-only verification against an explicitly selected local paper deployment.
import { execFileSync } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const base = process.env.NFI_RESEARCH_TEST_URL;
const container = process.env.NFI_RESEARCH_TEST_CONTAINER;
if (!base?.startsWith('http://127.0.0.1:') || !container)
  throw new Error('Specify the local paper URL and container explicitly');
const script = `
import json,os
from nfi_account.credentials import AccountManager
from freqtrade.rpc.api_server.api_auth import create_token
api={'username':os.environ['FREQTRADE__API_SERVER__USERNAME'],'jwt_secret_key':os.environ['FREQTRADE__API_SERVER__JWT_SECRET_KEY']}
AccountManager({'api_server':api,'user_data_dir':'/freqtrade/user_data'})
data={'identity':{'u':api['username']}}
print(json.dumps({'username':api['username'],'accessToken':create_token(data,api['jwt_secret_key']),'refreshToken':create_token(data,api['jwt_secret_key'],'refresh')}))
`;
const credentials = JSON.parse(
  execFileSync('docker', ['exec', container, 'python', '-c', script], { encoding: 'utf8' }),
);
const browser = await chromium.launch({
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  const writes = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method()))
      writes.push(new URL(request.url()).pathname);
  });
  await page.addInitScript(({ base, credentials }) => {
    localStorage.setItem('ftAuthLoginInfo', JSON.stringify({
      activityCheck: { ...credentials, botName: 'OKX 模拟盘', apiUrl: base, autoRefresh: true },
    }));
  }, { base, credentials });
  const headers = { Authorization: 'Bearer ' + credentials.accessToken };
  const unauthenticated = await page.request.get(base + '/api/v1/strategy-activity');
  expect(unauthenticated.status()).toBe(401);
  await expect.poll(async () => {
    try { return (await page.request.get(base + '/api/v1/strategy-activity', { headers })).status(); }
    catch { return 0; }
  }, { timeout: 90000, intervals: [2000] }).toBe(200);
  const response = await page.request.get(base + '/api/v1/strategy-activity', { headers });
  expect(response.status()).toBe(200);
  const data = await response.json();
  expect(data.exchange).toBe('okx');
  expect(data.dry_run).toBe(true);
  expect(data.state).toBe('stopped');
  expect(data.reasons).toContain('stopped');
  await page.goto(base + '/activity');
  await expect(page.getByRole('heading', { name: '策略动态', exact: true })).toBeVisible();
  await expect(page.getByText('机器人已停止：点击启动后才会分析策略并管理持仓。').first()).toBeVisible();
  await mkdir('../artifacts/activity-preview', { recursive: true });
  await page.screenshot({ path: '../artifacts/activity-preview/desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '../artifacts/activity-preview/mobile.png' });
  const research = await page.request.get(base + '/api/v1/research/info', { headers });
  expect(research.status()).toBe(200);
  expect((await research.json()).exchange).toBe('okx');
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
  console.log(`OKX paper verified: stopped, ${data.pair_count} pairs, ${data.fills.length} filled orders, authenticated read-only activity, desktop/mobile.`);
} finally {
  await browser.close();
}
