import { expect, test } from '@playwright/test';
import { login, mockBot } from './helpers';

for (const width of [1440, 390]) {
  test(`login blocks repeated submissions until freeze expiry at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.clock.install({ time: new Date('2026-11-08T00:00:00Z') });
    await page.clock.pauseAt(new Date('2026-11-08T00:01:00Z'));
    await mockBot(page);
    let attempts = 0;
    await page.route('**/api/v1/token/login', (route) => {
      attempts++;
      if (attempts < 5) return route.fulfill({ status: 401, json: { detail: 'Unauthorized' } });
      if (attempts === 5)
        return route.fulfill({
          status: 429,
          headers: { 'Retry-After': '3' },
          json: { detail: 'account_rate_limited', retry_after: 3 },
        });
      return route.fulfill({
        json: { access_token: 'test-access', refresh_token: 'test-refresh' },
      });
    });
    await page.goto('/login');
    await page.getByLabel('机器人名称', { exact: true }).fill('冻结测试');
    await page.getByLabel('用户名', { exact: true }).fill('paper');
    await page.getByLabel('密码', { exact: true }).fill('wrong-password');
    const submit = page.getByRole('button', { name: '提交', exact: true });
    for (let index = 0; index < 5; index++) {
      await submit.click();
      await expect.poll(() => attempts).toBe(index + 1);
      if (index < 4) await expect(submit).toBeEnabled();
    }
    await expect(
      page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结，请在 3 秒后重试。' }),
    ).toBeVisible();
    await expect(submit).toBeDisabled();
    await expect(page.getByLabel('密码', { exact: true })).toHaveValue('');
    await page.getByLabel('密码', { exact: true }).fill('correct-password');
    await page.getByLabel('密码', { exact: true }).press('Enter');
    expect(attempts).toBe(5);
    await page.getByRole('button', { name: '重置', exact: true }).click();
    await expect(submit).toBeDisabled();
    await page.clock.fastForward(1000);
    await expect(page.getByRole('alert').filter({ hasText: '2 秒后重试' })).toBeVisible();
    await page.clock.fastForward(2000);
    await expect(submit).toBeEnabled();
    await page.getByLabel('用户名', { exact: true }).fill('paper');
    await page.getByLabel('密码', { exact: true }).fill('correct-password');
    await submit.click();
    await expect(page).not.toHaveURL(/\/login/);
    expect(attempts).toBe(6);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
      /wrong-password|correct-password/,
    );
  });
}

test('settings share a countdown, stay online and restore the freeze after reload', async ({
  page,
}) => {
  await page.clock.install({ time: new Date('2026-11-08T00:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-08T00:01:00Z'));
  const trading = await mockBot(page);
  let frozen = false;
  await page.route('**/api/v1/account', (route) =>
    route.fulfill({
      json: {
        username: 'paper',
        password_protection: {
          max_failures: 5,
          window_seconds: 300,
          freeze_seconds: 300,
          retry_after: frozen ? 3 : 0,
        },
      },
    }),
  );
  await page.route('**/api/v1/startup-settings', (route) =>
    route.fulfill({
      json: { auto_start: true, revision: 0, role: 'paper', updated_at: null, can_enable: true },
    }),
  );
  let writes = 0;
  await page.route('**/api/v1/bark-settings', (route) => {
    if (route.request().method() === 'PUT') {
      writes++;
      frozen = true;
      return route.fulfill({
        status: 429,
        json: { detail: 'account_rate_limited', retry_after: 3 },
        headers: { 'Retry-After': '3' },
      });
    }
    return route.fulfill({
      json: {
        enabled: false,
        profit_enabled: true,
        profit_threshold_pct: 5,
        loss_enabled: true,
        loss_threshold_pct: 3,
        state_enabled: false,
        cooldown_minutes: 60,
        revision: 0,
        role: 'paper',
        destination_configured: false,
        updated_at: null,
        check_interval_seconds: 60,
        last_checked_at: null,
        roi_pct: null,
        bot_state: null,
        monitor_error: null,
        history: [],
      },
    });
  });
  await login(page);
  await page.goto('/settings');
  const bark = page.getByRole('region', { name: 'Bark 通知', exact: true });
  const startup = page.getByRole('region', { name: '机器人启动', exact: true });
  await bark.getByRole('spinbutton', { name: '收益率阈值（%）', exact: true }).fill('6');
  await bark.getByLabel('管理员密码（Bark 设置验证）', { exact: true }).fill('wrong-password');
  await bark.getByRole('button', { name: '保存 Bark 设置', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toBeVisible();
  expect(writes).toBe(1);
  await startup.getByRole('switch').click();
  await startup.getByLabel('当前管理员密码', { exact: true }).fill('correct-password');
  await expect(startup.getByRole('button', { name: '保存启动设置', exact: true })).toBeDisabled();
  await expect(bark.getByRole('button', { name: '保存 Bark 设置', exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toBeVisible();
  await page.clock.fastForward(3000);
  await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toHaveCount(0);
  await startup.getByRole('switch').click();
  await startup.getByLabel('当前管理员密码', { exact: true }).fill('correct-password');
  await expect(startup.getByRole('button', { name: '保存启动设置', exact: true })).toBeEnabled();
  expect(writes).toBe(1);
  expect(
    trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
  ).toEqual([]);
});

test('initial administrator setup displays its separate cooldown', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-11-08T00:00:00Z') });
  await page.clock.pauseAt(new Date('2026-11-08T00:01:00Z'));
  await mockBot(page);
  await page.route('**/api/v1/live/setup-status', (route) =>
    route.fulfill({ json: { required: true } }),
  );
  await page.route('**/api/v1/live/setup', (route) =>
    route.fulfill({ status: 429, json: { detail: 'account_rate_limited', retry_after: 3 } }),
  );
  await page.goto('/setup');
  await page.getByLabel('管理员用户名', { exact: true }).fill('admin');
  await page.getByLabel('管理员密码', { exact: true }).fill('fixture-setup-password');
  await page.getByLabel('确认管理员密码', { exact: true }).fill('fixture-setup-password');
  const submit = page.getByRole('button', { name: '创建账号并登录', exact: true });
  await submit.click();
  await expect(page.getByRole('alert').filter({ hasText: '密码验证已暂时冻结' })).toBeVisible();
  await expect(submit).toBeDisabled();
  await page.clock.fastForward(3000);
  await page.getByLabel('管理员密码', { exact: true }).fill('fixture-setup-password');
  await page.getByLabel('确认管理员密码', { exact: true }).fill('fixture-setup-password');
  await expect(submit).toBeEnabled();
});
