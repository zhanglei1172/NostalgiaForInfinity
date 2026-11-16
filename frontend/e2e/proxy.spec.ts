import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { ProxySettings } from '../src/types/proxy';

async function proxy(page: Page, blocked = false) {
  const trading = await mockBot(page);
  const settings: ProxySettings = {
    role: 'live',
    revision: 0,
    settings: {
      enabled: false,
      protocol: 'socks5h',
      host: '',
      port: 1080,
      auth_enabled: false,
      username_configured: false,
      password_configured: false,
    },
    active_revision: 0,
    active_enabled: false,
    runtime_revision: 0,
    runtime_enabled: false,
    pending_changes: false,
    updated_at: null,
    applied_at: null,
    can_apply: !blocked,
    apply_block_reason: blocked ? 'proxy_stop_required' : null,
  };
  const writes: { endpoint: string; body: Record<string, unknown> }[] = [];
  await page.route('**/api/v1/proxy-settings{,/check,/apply}', (route) => {
    const request = route.request();
    if (request.method() === 'GET') return route.fulfill({ json: settings });
    const body = request.postDataJSON();
    const endpoint = new URL(request.url()).pathname;
    writes.push({ endpoint, body });
    if (body.current_password !== 'fixture-proxy-admin')
      return route.fulfill({ status: 400, json: { detail: 'account_incorrect_password' } });
    if (endpoint.endsWith('/check'))
      return route.fulfill({
        json: {
          success: true,
          checked_at: new Date().toISOString(),
          checks: {
            rest_sync: { success: true, latency_ms: 15 },
            rest_async: { success: true, latency_ms: 16 },
            websocket: { success: true, latency_ms: 20 },
          },
        },
      });
    if (endpoint.endsWith('/apply')) {
      settings.active_revision = settings.runtime_revision = settings.revision;
      settings.active_enabled = settings.runtime_enabled = settings.settings.enabled;
      settings.pending_changes = false;
    } else {
      const { username, password, current_password: _admin, revision: _revision, ...fields } = body;
      expect(_admin).toBe('fixture-proxy-admin');
      expect(_revision).toBe(settings.revision);
      Object.assign(settings.settings, fields, {
        username_configured: fields.auth_enabled && !!username,
        password_configured: fields.auth_enabled && !!password,
      });
      settings.revision += 1;
      settings.pending_changes = true;
    }
    return route.fulfill({ json: settings });
  });
  await login(page);
  await page.goto('/settings');
  const panel = page.getByRole('region', { name: '交易所代理', exact: true });
  await expect(panel).toBeVisible();
  return { panel, settings, writes, trading };
}

for (const width of [1440, 390]) {
  test(`proxy draft, public test, explicit apply and secret handling at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    const { panel, settings, writes, trading } = await proxy(page);
    const admin = panel.getByLabel('管理员密码（代理设置验证）', { exact: true });
    const apply = panel.getByRole('button', { name: '应用已保存的连接设置', exact: true });
    await expect(panel.getByText('当前连接：直连', { exact: true })).toBeVisible();
    await panel.getByRole('switch', { name: '使用代理连接交易所', exact: true }).click();
    await panel.getByLabel('代理主机', { exact: true }).fill('host.docker.internal');
    await panel.getByRole('switch', { name: '代理需要用户名和密码', exact: true }).click();
    await panel.getByLabel('代理用户名', { exact: true }).fill('fixture-proxy-user');
    await panel.getByLabel('代理密码', { exact: true }).fill('fixture-proxy-password');
    await expect(apply).toBeDisabled();
    await admin.fill('fixture-proxy-admin');
    await panel.getByRole('button', { name: '测试交易所连接', exact: true }).click();
    await expect(panel.getByText('WebSocket K 线订阅', { exact: false })).toContainText('连接成功');
    expect(settings.active_enabled).toBe(false);
    await expect(panel.getByLabel('代理密码', { exact: true })).toHaveValue(
      'fixture-proxy-password',
    );
    await admin.fill('fixture-proxy-admin');
    await panel.getByRole('button', { name: '保存代理草稿', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('代理草稿已保存');
    await expect(panel.getByLabel('代理密码', { exact: true })).toHaveValue('');
    await expect(admin).toHaveValue('');
    expect(settings.active_enabled).toBe(false);
    await expect(panel.getByText('连接设置待应用或加载', { exact: true })).toBeVisible();
    await admin.fill('fixture-proxy-admin');
    await apply.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('机器人会保持停止');
    await dialog.getByRole('button', { name: '确定', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('已选择保存的连接设置');
    expect(settings.active_enabled).toBe(true);
    expect(writes.at(-1)).toEqual({
      endpoint: '/api/v1/proxy-settings/apply',
      body: { revision: 1, current_password: 'fixture-proxy-admin' },
    });
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
      /fixture-proxy-user|fixture-proxy-password|fixture-proxy-admin/,
    );
    expect(
      trading.filter((item) => !['token/login', 'pair_candles'].includes(item.endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('running bot may save a proxy draft but cannot apply it', async ({ page }) => {
  const { panel, writes } = await proxy(page, true);
  await expect(
    panel.getByText('请先停止机器人再应用代理设置。仍可保存草稿和测试连接。', { exact: true }),
  ).toBeVisible();
  await panel.getByRole('switch', { name: '使用代理连接交易所', exact: true }).click();
  await panel.getByLabel('代理主机', { exact: true }).fill('proxy.example.test');
  await panel.getByLabel('管理员密码（代理设置验证）', { exact: true }).fill('fixture-proxy-admin');
  await panel.getByRole('button', { name: '保存代理草稿', exact: true }).click();
  await expect(panel.getByRole('status')).toContainText('代理草稿已保存');
  await expect(
    panel.getByRole('button', { name: '应用已保存的连接设置', exact: true }),
  ).toBeDisabled();
  expect(writes).toHaveLength(1);
});
