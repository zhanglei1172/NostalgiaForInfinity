import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';

async function account(page: Page) {
  const requests = await mockBot(page);
  await page.route('**/api/v1/account', (route) =>
    route.fulfill({
      json: {
        username: 'paper',
        password_changed_at: null,
        sessions_revoked_at: null,
        min_password_length: 12,
        max_password_length: 128,
        refresh_token_days: 30,
      },
    }),
  );
  await login(page);
  await page.goto('/account');
  await expect(page.getByRole('heading', { name: '账户与安全', exact: true })).toBeVisible();
  return requests;
}

test('password form checks confirmation, reports a wrong current password, and signs out after success', async ({
  page,
}) => {
  await account(page);
  const form = page.locator('form').first();
  await form.getByLabel('当前密码', { exact: true }).fill('original-password');
  await form.getByLabel('新密码', { exact: true }).fill('new-password-2026');
  await form.getByLabel('确认新密码', { exact: true }).fill('does-not-match');
  const changed: unknown[] = [];
  await page.route('**/api/v1/account/password', async (route) => {
    changed.push(route.request().postDataJSON());
    return route.fulfill({ status: 400, json: { detail: 'account_incorrect_password' } });
  });
  await form.getByRole('button', { name: '保存密码并重新登录' }).click();
  await expect(page.getByText('两次输入的新密码不一致。', { exact: true })).toBeVisible();
  expect(changed).toHaveLength(0);
  await form.getByLabel('确认新密码', { exact: true }).fill('new-password-2026');
  await form.getByRole('button', { name: '保存密码并重新登录' }).click();
  await expect(page.getByText('当前密码不正确。', { exact: true })).toBeVisible();
  expect(changed).toEqual([
    { current_password: 'original-password', new_password: 'new-password-2026' },
  ]);
  await page.route('**/api/v1/account/password', (route) =>
    route.fulfill({ json: { success: true, reauthenticate: true } }),
  );
  await form.getByRole('button', { name: '保存密码并重新登录' }).click();
  await expect(page).toHaveURL(/\/login\?/);
  await expect(page.getByText('密码已更新，请使用新密码登录。', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toMatch(
    /original-password|new-password-2026/,
  );
  await expect(page.getByLabel('密码', { exact: true })).toHaveValue('');
});

test('sign out all devices requires a password and allows confirmation cancellation', async ({
  page,
}) => {
  await account(page);
  const sessions = page.locator('form').last();
  const requests: unknown[] = [];
  await page.route('**/api/v1/account/sessions/revoke', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: { success: true, reauthenticate: true } });
  });
  await sessions.getByLabel('当前密码', { exact: true }).fill('original-password');
  await sessions.getByRole('button', { name: '退出所有设备', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click();
  expect(requests).toEqual([]);
  await sessions.getByRole('button', { name: '退出所有设备', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(page.getByText('所有设备的登录已失效，请重新登录。', { exact: true })).toBeVisible();
  expect(requests).toEqual([{ current_password: 'original-password' }]);
});

test('account page supports mobile layout, password visibility and English labels', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await account(page);
  await page.screenshot({ path: testInfo.outputPath('account-mobile.png') });
  const form = page.locator('form').first();
  await form.getByLabel('新密码', { exact: true }).fill('a-visible-password');
  await form.getByRole('button', { name: '显示密码', exact: true }).nth(1).click();
  await expect(form.getByLabel('新密码', { exact: true })).toHaveAttribute('type', 'text');
  await form.getByRole('button', { name: '隐藏密码', exact: true }).click();
  await expect(form.getByLabel('新密码', { exact: true })).toHaveAttribute('type', 'password');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Account & security', exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('New password', { exact: true })).toHaveValue('');
});

test('legacy bots show a clear unsupported state and revoked sessions return to sign-in', async ({
  page,
}) => {
  await account(page);
  await page.route('**/api/v1/account', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Not Found' } }),
  );
  await page.reload();
  await expect(page.getByText('此机器人暂不支持账户管理。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存密码并重新登录' })).toHaveCount(0);
  await page.route('**/api/v1/token/refresh', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }),
  );
  await page.route('**/api/v1/account', (route) =>
    route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }),
  );
  await page.reload();
  await expect(page.getByText('登录已失效，请重新登录。', { exact: true })).toBeVisible();
  await expect(page.getByLabel('用户名', { exact: true })).toHaveValue('test-user');
});
