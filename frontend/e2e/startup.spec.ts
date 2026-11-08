import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { StartupSettings } from '../src/types/startup';

async function startup(page: Page, changes: Partial<StartupSettings> = {}) {
  const trading = await mockBot(page);
  const settings: StartupSettings = {
    auto_start: false,
    revision: 0,
    updated_at: null,
    role: 'paper',
    can_enable: true,
    ...changes,
  };
  const writes: Record<string, unknown>[] = [];
  await page.route('**/api/v1/startup-settings', (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON();
      writes.push(body);
      if (body.current_password !== 'fixture-startup-password')
        return route.fulfill({ status: 400, json: { detail: 'account_incorrect_password' } });
      Object.assign(settings, { auto_start: body.auto_start, revision: body.revision + 1 });
    }
    return route.fulfill({ json: settings });
  });
  await login(page);
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: '机器人启动', exact: true })).toBeVisible();
  return { writes, trading, settings };
}
const switchName = '容器启动／重启后自动启动机器人';

for (const width of [1440, 390]) {
  test(`startup preference is explicit, persistent and never changes trading now at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { writes, trading } = await startup(page);
    const toggle = page.getByRole('switch', { name: switchName, exact: true });
    const save = page.getByRole('button', { name: '保存启动设置', exact: true });
    const password = page.getByLabel('当前管理员密码', { exact: true });
    await expect(toggle).toHaveAttribute('aria-checked', 'false');
    await expect(save).toBeDisabled();
    await toggle.click();
    await expect(save).toBeDisabled();
    await password.fill('fixture-startup-password');
    await save.click();
    await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
    expect(writes).toEqual([]);
    await password.fill('wrong-password');
    await save.click();
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect(page.getByRole('alert').filter({ hasText: '当前密码不正确。' })).toBeVisible();
    await expect(password).toHaveValue('');
    await password.fill('fixture-startup-password');
    await save.click();
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: '启动设置已保存' })).toBeVisible();
    expect(writes.at(-1)).toEqual({
      auto_start: true,
      revision: 0,
      current_password: 'fixture-startup-password',
    });
    await expect(password).toHaveValue('');
    await page.reload();
    await expect(toggle).toHaveAttribute('aria-checked', 'true');
    await toggle.click();
    await password.fill('fixture-startup-password');
    await save.click();
    await expect(page.getByRole('status').filter({ hasText: '启动设置已保存' })).toBeVisible();
    expect(writes.at(-1)).toMatchObject({ auto_start: false, revision: 1 });
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
      'fixture-startup-password',
    );
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath(`startup-${width}.png`), fullPage: true });
    await page.getByRole('banner').getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Bot startup', exact: true })).toBeVisible();
  });
}

test('live startup requires a configured account and explicitly confirms automatic real orders', async ({
  page,
}) => {
  const { writes } = await startup(page, { role: 'live', can_enable: false });
  const toggle = page.getByRole('switch', { name: switchName, exact: true });
  await expect(toggle).toBeDisabled();
  await expect(
    page.getByText('请先配置实盘交易账户并成功加载，再开启自动启动。', { exact: true }),
  ).toBeVisible();
  await page.route('**/api/v1/startup-settings', (route) => {
    if (route.request().method() === 'PUT') {
      writes.push(route.request().postDataJSON());
      return route.fulfill({
        json: { role: 'live', can_enable: true, auto_start: true, revision: 1, updated_at: null },
      });
    }
    return route.fulfill({
      json: { role: 'live', can_enable: true, auto_start: false, revision: 0, updated_at: null },
    });
  });
  await page.getByRole('button', { name: '重新读取启动设置', exact: true }).click();
  await expect(toggle).toBeEnabled();
  await toggle.click();
  await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-startup-password');
  await page.getByRole('button', { name: '保存启动设置', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('真实订单');
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  expect(writes).toEqual([]);
});

test('stale startup revisions retain the draft and can recover using reload', async ({ page }) => {
  const { settings } = await startup(page);
  await page.route('**/api/v1/startup-settings', (route) => {
    if (route.request().method() === 'PUT') {
      Object.assign(settings, { auto_start: true, revision: 1 });
      return route.fulfill({ status: 409, json: { detail: 'startup_revision_conflict' } });
    }
    return route.fulfill({ json: settings });
  });
  await page.getByRole('switch', { name: switchName, exact: true }).click();
  await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-startup-password');
  await page.getByRole('button', { name: '保存启动设置', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '其他会话已修改启动设置' })).toBeVisible();
  await expect(page.getByRole('switch', { name: switchName, exact: true })).toHaveAttribute(
    'aria-checked',
    'true',
  );
  await page.getByRole('button', { name: '重新读取启动设置', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存启动设置', exact: true })).toBeDisabled();
});

test('unsupported bots do not offer a misleading browser-only startup switch', async ({ page }) => {
  await startup(page);
  await page.route('**/api/v1/startup-settings', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
  );
  await page.reload();
  await expect(
    page.getByText('此机器人暂不支持网页启动设置，请更新其 NFI 镜像后配置。'),
  ).toBeVisible();
  await expect(page.getByRole('switch', { name: switchName, exact: true })).toHaveCount(0);
});
