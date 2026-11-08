import { expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// All bot requests are mocked; these checks never send an order to a running bot.
export async function mockBot(page: Page) {
  await page.route(
    /https:\/\/(api\.iconify\.design|api\.simplesvg\.com|api\.unisvg\.com)\//,
    (route) => route.abort(),
  );
  const requests: { endpoint: string; body: unknown }[] = [];
  const fixtures: Record<string, string> = {
    ping: 'ping.json',
    show_config: 'show_config.json',
    status: 'status_empty.json',
    profit: 'profit.json',
    trades: 'trades.json',
    balance: 'balance.json',
    whitelist: 'whitelist.json',
    blacklist: 'blacklist.json',
    performance: 'performance.json',
    locks: 'locks_empty.json',
    logs: 'logs.json',
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.replace('/api/v1/', '');
    if (request.method() === 'POST') {
      requests.push({ endpoint, body: request.postDataJSON() });
    }
    if (endpoint === 'token/login') {
      return route.fulfill({
        json: { access_token: 'test-access', refresh_token: 'test-refresh' },
      });
    }
    if (endpoint === 'profit_all') {
      return route.fulfill({
        json: {
          all: JSON.parse(
            fs.readFileSync(path.join(import.meta.dirname, 'testData', 'profit.json'), 'utf8'),
          ),
        },
      });
    }
    const fixture = fixtures[endpoint];
    if (fixture) {
      const data = JSON.parse(
        fs.readFileSync(path.join(import.meta.dirname, 'testData', fixture), 'utf8'),
      );
      return route.fulfill({ json: data });
    }
    return route.fulfill({
      json: endpoint === 'count' ? { current: 0, max: 3, total_stake: 0 } : {},
    });
  });
  await page.routeWebSocket('**/api/v1/message/ws**', () => {});
  return requests;
}

export async function login(page: Page) {
  await page.goto('/login');
  await page.getByLabel('机器人名称', { exact: true }).fill('中文测试机器人');
  await page.getByLabel('用户名', { exact: true }).fill('test-user');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '提交', exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto('/trade');
  await expect(page.getByText('当前持仓', { exact: true }).first()).toBeVisible();
}
