import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { RecipeInfo, RecipeSettings } from '../src/types/recipe';

const defaults: RecipeSettings = JSON.parse(
  readFileSync(
    new URL('../../webserver_extensions/nfi_research/recipe_defaults.json', import.meta.url),
    'utf8',
  ),
);
async function mockRecipe(page: Page) {
  const trading = await mockBot(page);
  const state: RecipeInfo = {
    exchange: 'okx',
    saved: { revision: 0, settings: structuredClone(defaults) },
    defaults,
    applied_revision: 0,
    applied_settings: structuredClone(defaults),
    can_apply: true,
  };
  const writes: { method: string; path: string; body: unknown }[] = [];
  await page.route('**/api/v1/recipe**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'PUT') {
      const body = request.postDataJSON();
      writes.push({ method: 'PUT', path, body });
      state.saved = { revision: body.revision + 1, settings: body.settings };
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      writes.push({ method: 'POST', path, body });
      state.applied_revision = body.revision;
      state.applied_settings = structuredClone(state.saved.settings);
      return route.fulfill({ json: { status: 'reloading', requested_revision: body.revision } });
    }
    return route.fulfill({ json: state });
  });
  await login(page);
  if ((page.viewportSize()?.width ?? 1440) < 1024)
    await page.getByRole('button', { name: '打开导航', exact: true }).click();
  await page.getByRole('link', { name: '策略配方', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: '策略配方', exact: true })).toBeVisible();
  return { state, writes, trading };
}

test('recipe saves bounded percentages and applies separately without trading controls', async ({
  page,
}) => {
  const { writes, trading } = await mockRecipe(page);
  const save = page.getByRole('button', { name: '保存用于回测', exact: true });
  const apply = page.getByRole('button', { name: '应用到模拟盘', exact: true });
  await expect(save).toBeDisabled();
  await page.getByLabel('最大持仓数', { exact: true }).fill('8');
  await page.getByLabel('单边手续费（%）', { exact: true }).fill('0.15');
  await page.getByRole('heading', { name: '策略配方', exact: true }).click();
  await expect(apply).toBeDisabled();
  await save.click();
  await expect(
    page.getByRole('status').filter({ hasText: '已保存。下一次下载行情和回测会使用此配方。' }),
  ).toBeVisible();
  expect(writes[0]?.body).toMatchObject({
    revision: 0,
    settings: { max_open_trades: 8, fee: 0.0015 },
  });
  expect(writes).toHaveLength(1);
  await apply.click();
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(page.getByText('已保存的配方已在模拟盘生效。', { exact: true })).toBeVisible({
    timeout: 15000,
  });
  expect(writes[1]).toEqual({
    method: 'POST',
    path: '/api/v1/recipe/apply',
    body: { revision: 1 },
  });
  await page.reload();
  await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue('8');
  expect(
    trading.filter((request) => !['token/login', 'pair_candles'].includes(request.endpoint)),
  ).toEqual([]);
});

test('recipe rejects duplicate symbols and restores defaults on mobile', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockRecipe(page);
  const pairs = page.getByLabel('固定回测币池', { exact: true });
  await pairs.fill('BTC/USDT\nBTC/USDT\nETH/USDT');
  await expect(page.getByRole('button', { name: '保存用于回测', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '恢复默认值', exact: true }).click();
  await expect(pairs).toHaveValue(defaults.research_pairs.join('\n'));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('recipe-mobile.png'), fullPage: true });
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Recipe settings', exact: true })).toBeVisible();
});

test('a stale saved revision keeps the edited form available for recovery', async ({ page }) => {
  await mockRecipe(page);
  await page.route('**/api/v1/recipe', (route) =>
    route.request().method() === 'PUT'
      ? route.fulfill({ status: 409, json: { detail: 'recipe_revision_conflict' } })
      : route.fallback(),
  );
  await page.getByLabel('最大持仓数', { exact: true }).fill('10');
  await page.getByRole('heading', { name: '策略配方', exact: true }).click();
  await page.getByRole('button', { name: '保存用于回测', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('配方已被其他会话更新');
  await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue('10');
  await expect(page.getByRole('button', { name: '应用到模拟盘', exact: true })).toBeDisabled();
});
