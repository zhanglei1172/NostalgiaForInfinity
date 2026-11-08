import { expect, test } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { LiveSettings } from '../src/types/live';
import fs from 'node:fs';

test('fresh live service creates the administrator entirely through Web setup', async ({
  page,
}) => {
  await mockBot(page);
  let required = true;
  const registrations: unknown[] = [];
  await page.route('**/api/v1/live/setup-status', (route) => route.fulfill({ json: { required } }));
  await page.route('**/api/v1/live/setup', (route) => {
    registrations.push(route.request().postDataJSON());
    required = false;
    return route.fulfill({ json: { success: true } });
  });
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: '创建管理员账号', exact: true })).toBeVisible();
  const submit = page.getByRole('button', { name: '创建账号并登录', exact: true });
  await expect(submit).toBeDisabled();
  await page.getByLabel('管理员用户名', { exact: true }).fill('live-admin');
  await page.getByLabel('管理员密码', { exact: true }).fill('fixture-web-password');
  await page.getByLabel('确认管理员密码', { exact: true }).fill('mismatch');
  await expect(submit).toBeDisabled();
  await page.getByLabel('确认管理员密码', { exact: true }).fill('fixture-web-password');
  await submit.click();
  await expect(page).toHaveURL(/\/login\?/);
  await expect(page.getByText('管理员已创建，请登录后配置交易账户。')).toBeVisible();
  expect(registrations).toEqual([{ username: 'live-admin', password: 'fixture-web-password' }]);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'fixture-web-password',
  );
});

for (const width of [1440, 390]) {
  test(`account credentials and budget are configured privately on Web at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const trading = await mockBot(page);
    const settings: LiveSettings = {
      configured: false,
      exchange: 'okx',
      revision: 0,
      runtime_revision: 0,
      phase: 'setup',
      error: null,
      account_label: 'OKX',
      account_uid: null,
      available_capital: null,
      credentials_configured: false,
      updated_at: null,
      recipe_revision: null,
      state: 'unconfigured',
      database: { trades: 0, open_trades: 0, open_orders: 0 },
    };
    const balance = {
      uid: '123456789',
      free: 10000,
      used: 50,
      total: 10050,
      checked_at: '2026-11-08T02:00:00Z',
    };
    const requests: { path: string; body: Record<string, unknown> }[] = [];
    await page.route('**/api/v1/live-settings**', (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST') {
        requests.push({ path, body: request.postDataJSON() });
        return route.fulfill({ json: balance });
      }
      if (request.method() === 'PUT') {
        const body = request.postDataJSON();
        requests.push({ path, body });
        Object.assign(settings, {
          configured: true,
          revision: body.revision + 1,
          runtime_revision: body.revision + 1,
          phase: 'ready',
          account_label: body.account_label,
          available_capital: body.available_capital,
          credentials_configured: true,
          recipe_revision: 1,
          state: 'stopped',
          account_uid: balance.uid,
        });
        return route.fulfill({
          json: { saved: true, revision: settings.revision, state: 'stopped', balance },
        });
      }
      return route.fulfill({ json: settings });
    });
    await login(page);
    await page.goto('/trading_settings');
    await expect(page.getByRole('heading', { name: '交易账户', exact: true })).toBeVisible();
    await expect(
      page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }),
    ).toBeDisabled();
    await page.getByLabel('账户别名', { exact: true }).fill('OKX 专用账户');
    await page.getByLabel('初始交易预算（USDT）', { exact: true }).fill('1250');
    for (const [label, value] of [
      ['OKX API Key', 'fixture-key'],
      ['OKX API Secret', 'fixture-secret'],
      ['OKX API Passphrase', 'fixture-passphrase'],
    ]) {
      const input = page.getByLabel(label!, { exact: true });
      await input.fill(value!);
      await expect(input).toHaveAttribute('type', 'password');
    }
    await page.getByRole('button', { name: '验证连接并读取余额', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'OKX 交易账户余额', exact: true }),
    ).toBeVisible();
    await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-web-password');
    await page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect(
      page.getByRole('status').filter({ hasText: '账户配置已生效，机器人保持停止' }),
    ).toBeVisible();
    for (const label of ['OKX API Key', 'OKX API Secret', 'OKX API Passphrase', '当前管理员密码'])
      await expect(page.getByLabel(label, { exact: true })).toHaveValue('');
    expect(requests[0]).toMatchObject({
      path: '/api/v1/live-settings/check',
      body: {
        api_key: 'fixture-key',
        api_secret: 'fixture-secret',
        passphrase: 'fixture-passphrase',
      },
    });
    expect(requests[1]?.body).toMatchObject({
      account_label: 'OKX 专用账户',
      available_capital: 1250,
      revision: 0,
      current_password: 'fixture-web-password',
    });
    await page.reload();
    await expect(page.getByLabel('初始交易预算（USDT）', { exact: true })).toHaveAttribute(
      'aria-valuenow',
      '1250',
    );
    await expect(page.getByLabel('OKX API Key', { exact: true })).toHaveValue('');
    await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-web-password');
    await page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect.poll(() => requests.length).toBe(3);
    expect(requests[2]?.body).not.toHaveProperty('api_key');
    expect(requests[2]?.body).not.toHaveProperty('api_secret');
    expect(requests[2]?.body).not.toHaveProperty('passphrase');
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
      /fixture-(?:key|secret|passphrase|web-password)/,
    );
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`live-settings-${width}.png`),
      fullPage: true,
    });
    await page.getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Trading account', exact: true })).toBeVisible();
  });
}

test('account origin rejection explains the failure without exposing credentials', async ({
  page,
}) => {
  await mockBot(page);
  await page.route('**/api/v1/live-settings', (route) =>
    route.fulfill({
      json: {
        configured: false,
        exchange: 'okx',
        revision: 0,
        runtime_revision: 0,
        phase: 'setup',
        error: null,
        account_label: 'OKX',
        account_uid: null,
        available_capital: null,
        credentials_configured: false,
        updated_at: null,
        recipe_revision: null,
        state: 'unconfigured',
        database: { trades: 0, open_trades: 0, open_orders: 0 },
      },
    }),
  );
  await page.route('**/api/v1/live-settings/check', (route) =>
    route.fulfill({ status: 403, json: { detail: 'live_origin_rejected' } }),
  );
  await login(page);
  await page.goto('/trading_settings');
  for (const [label, value] of [
    ['OKX API Key', 'fixture-key'],
    ['OKX API Secret', 'fixture-secret'],
    ['OKX API Passphrase', 'fixture-passphrase'],
  ])
    await page.getByLabel(label!, { exact: true }).fill(value!);
  await page.getByRole('button', { name: '验证连接并读取余额', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('请求来源校验失败');
  await expect(page.getByRole('alert')).toContainText('反向代理');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
    /fixture-(?:key|secret|passphrase)/,
  );
});

test('live management login and dashboard redirect avoid unavailable trading RPC calls', async ({
  page,
}) => {
  await mockBot(page);
  const errors: string[] = [];
  const unavailable: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const config = JSON.parse(
    fs.readFileSync(new URL('./testData/show_config.json', import.meta.url), 'utf8'),
  );
  await page.route('**/api/v1/show_config', (route) =>
    route.fulfill({
      json: {
        ...config,
        runmode: 'webserver',
        dry_run: false,
        state: 'stopped',
        nfi_live_management: true,
        nfi_live_configured: false,
      },
    }),
  );
  await page.route('**/api/v1/live-settings', (route) =>
    route.fulfill({
      json: {
        configured: false,
        exchange: 'okx',
        revision: 0,
        runtime_revision: 0,
        phase: 'setup',
        error: null,
        account_label: 'OKX',
        account_uid: null,
        available_capital: null,
        credentials_configured: false,
        updated_at: null,
        recipe_revision: null,
        state: 'unconfigured',
        database: { trades: 0, open_trades: 0, open_orders: 0 },
      },
    }),
  );
  await page.route(
    /\/api\/v1\/(profit(?:_all)?|trades|status|balance|historic_balance|whitelist|blacklist|locks|daily)(?:\?|$)/,
    (route) => {
      unavailable.push(route.request().url());
      return route.fulfill({ status: 503, json: { detail: 'Bot is not in the correct state' } });
    },
  );
  await page.goto('/login');
  await page.getByLabel('机器人名称', { exact: true }).fill('实盘配置测试');
  await page.getByLabel('用户名', { exact: true }).fill('test-user');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '提交', exact: true }).click();
  await expect(page.getByRole('heading', { name: '交易账户', exact: true })).toBeVisible();
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/trading_settings$/);
  await expect(page.getByRole('heading', { name: '交易账户', exact: true })).toBeVisible();
  expect(unavailable).toEqual([]);
  expect(errors).toEqual([]);
});

test('paper connections explain that public data needs no exchange credentials', async ({
  page,
}) => {
  await mockBot(page);
  await login(page);
  await page.goto('/trading_settings');
  await expect(
    page.getByText(
      '此机器人使用公开行情进行模拟交易，无需交易所密钥。请连接实盘管理服务后配置交易账户。',
    ),
  ).toBeVisible();
  await expect(page.getByLabel('OKX API Secret', { exact: true })).toHaveCount(0);
});
