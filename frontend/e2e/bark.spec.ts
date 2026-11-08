import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { BarkSettings } from '../src/types/bark';

async function bark(page: Page, role: 'paper' | 'live' = 'paper') {
  const trading = await mockBot(page);
  const settings: BarkSettings = {
    enabled: false,
    profit_enabled: true,
    profit_threshold_pct: 5,
    loss_enabled: true,
    loss_threshold_pct: 3,
    state_enabled: false,
    trade_error_enabled: false,
    exchange_error_enabled: false,
    recovery_enabled: false,
    exchange_grace_minutes: 2,
    cooldown_minutes: 60,
    revision: 0,
    updated_at: null,
    role,
    destination_configured: false,
    check_interval_seconds: 60,
    last_checked_at: null,
    roi_pct: null,
    bot_state: null,
    monitor_error: null,
    history: [],
    operational_events_supported: true,
    active_incidents: [],
  };
  const writes: { method: string; body: Record<string, unknown> }[] = [];
  await page.route('**/api/v1/bark-settings{,/test}', (route) => {
    const method = route.request().method();
    if (method !== 'GET') {
      const body = route.request().postDataJSON();
      writes.push({ method, body });
      if (body.current_password !== 'fixture-bark-admin-password')
        return route.fulfill({ status: 400, json: { detail: 'account_incorrect_password' } });
      if (method === 'PUT') {
        const { current_password: _password, destination, clear_destination, ...rules } = body;
        expect(_password).toBe('fixture-bark-admin-password');
        Object.assign(settings, rules, {
          revision: settings.revision + 1,
          destination_configured: clear_destination
            ? false
            : !!destination || settings.destination_configured,
        });
      } else {
        settings.history = [
          { at: new Date().toISOString(), event: 'test', success: true, error: null },
        ];
      }
    }
    return route.fulfill({ json: settings });
  });
  await login(page);
  await page.goto('/settings');
  const panel = page.getByRole('region', { name: 'Bark 通知', exact: true });
  await expect(panel).toBeVisible();
  return { settings, writes, trading, panel };
}

for (const width of [1440, 390]) {
  test(`admin saves private Bark rules and tests the saved destination at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { panel, settings, writes, trading } = await bark(page);
    const enabled = panel.getByRole('switch', { name: '开启 Bark 通知', exact: true });
    const url = panel.getByLabel('Bark 推送地址', { exact: true });
    const password = panel.getByLabel('管理员密码（Bark 设置验证）', { exact: true });
    const save = panel.getByRole('button', { name: '保存 Bark 设置', exact: true });
    const send = panel.getByRole('button', { name: '发送 Bark 测试通知', exact: true });
    await expect(enabled).toHaveAttribute('aria-checked', 'false');
    await enabled.click();
    await expect(save).toBeDisabled();
    await url.fill('https://bark.fixture.test/private-device-key');
    await panel.getByRole('spinbutton', { name: '收益率阈值（%）', exact: true }).fill('8');
    await panel.getByRole('checkbox', { name: '机器人状态变化', exact: true }).click();
    await password.fill('wrong-password');
    await save.click();
    await expect(panel.getByRole('alert').filter({ hasText: '当前密码不正确。' })).toBeVisible();
    await expect(password).toHaveValue('');
    await expect(url).toHaveValue('');
    await url.fill('https://bark.fixture.test/private-device-key');
    await password.fill('fixture-bark-admin-password');
    await save.click();
    await expect(panel.getByRole('status')).toContainText('Bark 通知设置已保存。');
    await expect(url).toHaveValue('');
    await expect(password).toHaveValue('');
    expect(writes.at(-1)?.body).toMatchObject({
      enabled: true,
      profit_threshold_pct: 8,
      loss_threshold_pct: 3,
      state_enabled: true,
      revision: 0,
    });
    await password.fill('fixture-bark-admin-password');
    await send.click();
    await expect(panel.getByRole('status')).toContainText('Bark 已接收测试通知');
    expect(writes.at(-1)).toEqual({
      method: 'POST',
      body: { revision: 1, current_password: 'fixture-bark-admin-password' },
    });
    await expect(panel.getByText('Bark 已接收', { exact: true })).toBeVisible();
    await page.reload();
    await expect(enabled).toHaveAttribute('aria-checked', 'true');
    await expect(url).toHaveValue('');
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
      /private-device-key|fixture-bark-admin-password/,
    );
    await enabled.click();
    await password.fill('fixture-bark-admin-password');
    await save.click();
    expect(settings.enabled).toBe(false);
    expect(settings.destination_configured).toBe(true);
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await panel.screenshot({ path: testInfo.outputPath(`bark-${width}.png`) });
    await page.getByRole('banner').getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Bark notifications', exact: true }),
    ).toBeVisible();
  });
}

test('unconfigured live bot can save Bark independently and displays safe waiting status', async ({
  page,
}) => {
  const { panel, settings, writes } = await bark(page, 'live');
  settings.destination_configured = true;
  settings.enabled = true;
  settings.revision = 3;
  settings.monitor_error = 'bark_bot_not_ready';
  await panel.getByRole('button', { name: '刷新 Bark 设置', exact: true }).click();
  await expect(panel.getByText('实盘交易', { exact: true })).toBeVisible();
  await expect(panel.getByText('等待交易账户完成初始化。', { exact: true })).toBeVisible();
  await panel.getByRole('switch', { name: '开启 Bark 通知', exact: true }).click();
  await panel
    .getByLabel('管理员密码（Bark 设置验证）', { exact: true })
    .fill('fixture-bark-admin-password');
  await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
  expect(writes.at(-1)?.body).toMatchObject({ enabled: false, destination: '', revision: 3 });
});

test('stale Bark edits stay visible and never leak the saved destination', async ({ page }) => {
  const { panel } = await bark(page);
  await page.route('**/api/v1/bark-settings', (route) =>
    route.fulfill({ status: 409, json: { detail: 'bark_revision_conflict' } }),
  );
  await panel.getByRole('switch', { name: '开启 Bark 通知', exact: true }).click();
  await panel.getByLabel('Bark 推送地址', { exact: true }).fill('https://bark.fixture.test/key');
  await panel
    .getByLabel('管理员密码（Bark 设置验证）', { exact: true })
    .fill('fixture-bark-admin-password');
  await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('Bark 设置已在其他会话中修改');
  await expect(panel.getByLabel('Bark 推送地址', { exact: true })).toHaveValue('');
  await expect(panel.getByRole('switch', { name: '开启 Bark 通知', exact: true })).toHaveAttribute(
    'aria-checked',
    'true',
  );
});

test('Bark origin rejection explains how to access the correct bot', async ({ page }) => {
  const { panel } = await bark(page, 'live');
  await page.route('**/api/v1/bark-settings', async (route) => {
    if (route.request().method() === 'GET') return route.fallback();
    return route.fulfill({ status: 403, json: { detail: 'bark_origin_rejected' } });
  });
  await panel.getByRole('switch', { name: '开启 Bark 通知', exact: true }).click();
  await panel.getByLabel('Bark 推送地址', { exact: true }).fill('https://bark.fixture.test/key');
  await panel
    .getByLabel('管理员密码（Bark 设置验证）', { exact: true })
    .fill('fixture-bark-admin-password');
  await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('请求来源校验失败');
  await expect(panel.getByRole('alert')).toContainText('反向代理');
  await expect(panel.getByLabel('管理员密码（Bark 设置验证）', { exact: true })).toHaveValue('');
});

for (const width of [1440, 390]) {
  test(`admin configures order and connection alerts with recovery at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const { panel, settings, writes, trading } = await bark(page, 'live');
    await panel.getByRole('switch', { name: '开启 Bark 通知', exact: true }).click();
    await panel.getByRole('checkbox', { name: '收益达标', exact: true }).uncheck();
    await panel.getByRole('checkbox', { name: '亏损达标', exact: true }).uncheck();
    await panel.getByRole('checkbox', { name: '订单操作失败', exact: true }).check();
    await panel.getByRole('checkbox', { name: '交易所连接或初始化失败', exact: true }).check();
    await panel.getByRole('checkbox', { name: '已告警的连接问题恢复时通知', exact: true }).check();
    await panel
      .getByRole('spinbutton', { name: '连接异常通知延迟（分钟）', exact: true })
      .fill('3');
    await panel
      .getByLabel('Bark 推送地址', { exact: true })
      .fill('https://bark.fixture.test/device-key');
    await panel
      .getByLabel('管理员密码（Bark 设置验证）', { exact: true })
      .fill('fixture-bark-admin-password');
    await panel.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('Bark 通知设置已保存');
    expect(writes.at(-1)?.body).toMatchObject({
      profit_enabled: false,
      loss_enabled: false,
      trade_error_enabled: true,
      exchange_error_enabled: true,
      recovery_enabled: true,
      exchange_grace_minutes: 3,
    });
    settings.history = [
      {
        at: new Date().toISOString(),
        event: 'trade_error',
        success: true,
        error: null,
        context: { code: 'order_uncertain', operation: 'create_order', pair: 'BTC/USDT', count: 1 },
      },
    ];
    settings.active_incidents = [
      {
        code: 'authentication',
        operation: 'get_balances',
        pair: null,
        since: Date.now() / 1000,
        at: Date.now() / 1000,
      },
    ];
    await panel.getByRole('button', { name: '刷新 Bark 设置', exact: true }).click();
    await expect(panel.getByText('已记录的连接异常', { exact: true })).toBeVisible();
    await expect(panel.getByRole('listitem').filter({ hasText: '交易所身份验证或权限检查失败' })).toBeVisible();
    await expect(
      panel.getByText('订单请求发生网络异常，执行结果尚待机器人核对。', { exact: false }),
    ).toBeVisible();
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
      /device-key|fixture-bark-admin-password/,
    );
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}
