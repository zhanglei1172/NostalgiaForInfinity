import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { login, mockBot } from './helpers';

for (const width of [1440, 390]) {
  test(`deployment guide validates isolated futures commands at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await mockBot(page);
    await page.goto('/bots');
    await expect(page.getByRole('heading', { name: '机器人管理', exact: true })).toBeVisible();
    const command = page.getByTestId('deployment-command');
    await expect(command).toContainText("--name 'okx-futures' --mode futures --port 18082");
    await expect(command).toContainText('compose.json up -d bot');
    await page.getByLabel('实例名称', { exact: true }).fill('../escape');
    await expect(command).toHaveCount(0);
    await page.getByLabel('实例名称', { exact: true }).fill('second-futures');
    await expect(command).toContainText('user_data/bots/second-futures/compose.json');
    await expect(
      page.getByText(
        '每个机器人使用独立实例和 OKX 子账户。同一账户创建两组 API Key 不会隔离资金。',
        {
          exact: true,
        },
      ),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath(`bots-${width}.png`), fullPage: true });
  });
}

test('switching two bots clears account secrets and futures confirmation and targets only the selected bot', async ({
  page,
}) => {
  await mockBot(page);
  const config = JSON.parse(
    fs.readFileSync(new URL('./testData/show_config.json', import.meta.url), 'utf8'),
  );
  const writes: { host: string; body: Record<string, unknown> }[] = [];
  await page.route('**/api/v1/show_config', (route) =>
    route.fulfill({
      json: {
        ...config,
        dry_run: false,
        state: 'stopped',
        nfi_live_management: true,
        nfi_live_configured: true,
        trading_mode:
          new URL(route.request().url()).hostname === 'futures.example.test' ? 'futures' : 'spot',
      },
    }),
  );
  await page.route('**/api/v1/live-settings', (route) => {
    const request = route.request();
    const host = new URL(request.url()).hostname;
    const futures = host === 'futures.example.test';
    if (request.method() === 'PUT') {
      writes.push({ host, body: request.postDataJSON() });
      return route.fulfill({ json: { saved: true, revision: 2, state: 'stopped', balance: {} } });
    }
    return route.fulfill({
      json: {
        configured: true,
        exchange: 'okx',
        revision: 1,
        runtime_revision: 1,
        phase: 'ready',
        error: null,
        account_label: futures ? '合约账户' : '现货账户',
        available_capital: futures ? 500 : 1000,
        account_uid: futures ? '222' : '111',
        credentials_configured: true,
        state: 'stopped',
        database: { trades: 0, open_trades: 0, open_orders: 0 },
        trading_mode: futures ? 'futures' : 'spot',
        margin_mode: futures ? 'isolated' : '',
        leverage: 1,
        mode_locked: true,
      },
    });
  });
  await login(page);
  await page.goto('/bots');
  await page.getByRole('button', { name: '连接已有机器人', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('机器人名称', { exact: true }).fill('独立合约机器人');
  await dialog.locator('#url-input').fill('http://futures.example.test');
  await dialog.getByLabel('用户名', { exact: true }).fill('futures-admin');
  await dialog.getByLabel('密码', { exact: true }).fill('futures-password');
  await dialog.getByRole('button', { name: '提交', exact: true }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('article')).toHaveCount(2);
  await page.goto('/trading_settings');
  await expect(page.getByLabel('账户别名', { exact: true })).toHaveValue('合约账户');
  await expect(page.getByLabel('合约杠杆倍数', { exact: true })).toBeVisible();
  await page.getByLabel('OKX API Key', { exact: true }).fill('unsubmitted-futures-key');
  await page.getByLabel('当前管理员密码', { exact: true }).fill('private-admin-password');
  const acknowledgement = page.getByRole('checkbox', {
    name: '我确认这是独立的逐仓合约机器人，了解杠杆、资金费及强平会影响交易结果。',
  });
  await expect(
    page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }),
  ).toBeDisabled();
  await acknowledgement.check();
  await page.goto('/bots');
  await page
    .locator('article')
    .filter({ hasText: '中文测试机器人' })
    .getByRole('button', { name: '进入工作台', exact: true })
    .click();
  await page.goto('/trading_settings');
  await expect(page.getByLabel('账户别名', { exact: true })).toHaveValue('现货账户');
  await expect(page.getByLabel('OKX API Key', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('当前管理员密码', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('合约杠杆倍数', { exact: true })).toHaveCount(0);
  await page.getByLabel('当前管理员密码', { exact: true }).fill('spot-admin-password');
  await page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('中文测试机器人');
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]?.host).toBe('127.0.0.1');
  expect(writes[0]?.body).toMatchObject({ trading_mode: 'spot', available_capital: 1000 });
  expect(writes[0]?.body).not.toHaveProperty('api_key');
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    'unsubmitted-futures-key',
  );
  await page.goto('/bots');
  await page
    .locator('article')
    .filter({ hasText: '独立合约机器人' })
    .getByRole('button', { name: '进入工作台', exact: true })
    .click();
  await page.goto('/trading_settings');
  await expect(acknowledgement).not.toBeChecked();
  await expect(page.getByLabel('OKX API Key', { exact: true })).toHaveValue('');
  await page.getByLabel('合约杠杆倍数', { exact: true }).fill('2');
  await page.getByLabel('当前管理员密码', { exact: true }).fill('futures-admin-password');
  await acknowledgement.check();
  await page.getByRole('button', { name: '保存并应用（保持停止）', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('独立合约机器人');
  await expect(page.getByRole('dialog')).toContainText('逐仓合约');
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]?.host).toBe('futures.example.test');
  expect(writes[1]?.body).toMatchObject({
    trading_mode: 'futures',
    available_capital: 500,
    leverage: 2,
    confirm_futures: true,
  });
});
