import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { mockBot } from './helpers';
import type { LiveRecipeInfo, RecipeSettings } from '../src/types/recipe';

const defaults: RecipeSettings = JSON.parse(
  readFileSync(
    new URL('../../webserver_extensions/nfi_research/recipe_defaults.json', import.meta.url),
    'utf8',
  ),
);
const config = JSON.parse(
  readFileSync(new URL('./testData/show_config.json', import.meta.url), 'utf8'),
);

async function workspace(page: Page, configured = true) {
  const trading = await mockBot(page);
  await page.route('**/api/v1/show_config', (route) =>
    route.fulfill({
      json: {
        ...config,
        runmode: configured ? 'live' : 'webserver',
        dry_run: false,
        state: 'stopped',
        nfi_live_management: true,
        nfi_live_configured: configured,
      },
    }),
  );
  const state: LiveRecipeInfo = {
    exchange: 'okx',
    configured,
    saved: { revision: 0, settings: structuredClone(defaults) },
    defaults,
    applied_revision: null,
    applied_settings: configured ? structuredClone(defaults) : null,
    runtime_settings: configured ? structuredClone(defaults) : null,
    runtime_revision: null,
    live_revision: configured ? 1 : 0,
    runtime_live_revision: configured ? 1 : 0,
    phase: configured ? 'ready' : 'setup',
    error: null,
    can_apply: configured,
    apply_blocker: configured ? null : 'live_recipe_account_required',
    can_rollback: false,
    previous: null,
    paper_applied: { revision: 7, settings: { ...structuredClone(defaults), max_open_trades: 10 } },
    paper_saved: { revision: 8, settings: { ...structuredClone(defaults), max_open_trades: 12 } },
    live_fields: [
      'max_open_trades',
      'pair_limit',
      'min_age_days',
      'min_quote_volume',
      'max_spread_ratio',
      'max_slippage',
    ],
    strategy: {
      name: 'NostalgiaForInfinityX8',
      live_sha256: configured ? 'a'.repeat(64) : null,
      research_sha256: 'a'.repeat(64),
      matches: configured ? true : null,
    },
  };
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let loading = 0;
  await page.route('**/api/v1/live-recipe**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'PUT') {
      const body = request.postDataJSON();
      writes.push({ path, body });
      state.saved = { revision: body.revision + 1, settings: body.settings };
    }
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      writes.push({ path, body });
      if (body.current_password !== 'fixture-web-password')
        return route.fulfill({ status: 400, json: { detail: 'account_incorrect_password' } });
      const previous = structuredClone(state.applied_settings!);
      if (path.endsWith('/rollback'))
        state.saved = {
          revision: state.saved.revision + 1,
          settings: structuredClone(state.previous!.settings),
        };
      state.previous = { revision: state.applied_revision ?? 0, settings: previous };
      state.applied_revision = state.saved.revision;
      state.applied_settings = structuredClone(state.saved.settings);
      state.live_revision += 1;
      state.phase = 'applying';
      loading = 1;
      return route.fulfill({
        json: {
          status: 'reloading',
          requested_revision: state.saved.revision,
          live_revision: state.live_revision,
          state: 'stopped',
        },
      });
    }
    if (state.phase === 'applying' && loading-- <= 0) {
      state.phase = 'ready';
      state.runtime_live_revision = state.live_revision;
      state.runtime_revision = state.applied_revision;
      state.runtime_settings = structuredClone(state.applied_settings);
      state.can_rollback = true;
    }
    return route.fulfill({ json: state });
  });
  await page.goto('/login');
  await page.getByLabel('机器人名称', { exact: true }).fill('实盘配方测试');
  await page.getByLabel('用户名', { exact: true }).fill('test-user');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '提交', exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.goto('/recipes');
  await expect(
    page.getByRole('heading', { name: '实盘配置与模拟盘对比', exact: true }),
  ).toBeVisible();
  return { state, writes, trading };
}

for (const width of [1440, 390]) {
  test(`live recipe separates drafts, confirms apply and rollback at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { state, writes, trading } = await workspace(page);
    const apply = page.getByRole('button', { name: '应用到实盘（保持停止）', exact: true });
    await expect(apply).toBeDisabled();
    await page.getByLabel('最大持仓数', { exact: true }).fill('8');
    await page.getByRole('heading', { name: '编辑实盘草稿', exact: true }).click();
    await expect(apply).toBeDisabled();
    await page.getByRole('button', { name: '保存实盘草稿', exact: true }).click();
    await expect(
      page.getByText('实盘草稿已保存，当前实盘配置和模拟盘配方未改变。', { exact: true }),
    ).toBeVisible();
    expect(state.applied_settings?.max_open_trades).toBe(6);
    expect(state.paper_applied.settings.max_open_trades).toBe(10);
    await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-web-password');
    await apply.click();
    await expect(page.getByRole('dialog')).toContainText('真实交易');
    expect(writes).toHaveLength(1);
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect(
      page.getByText('实盘配方已生效，机器人保持停止。请核对后再手动启动。', { exact: true }),
    ).toBeVisible({ timeout: 15000 });
    expect(writes[1]).toEqual({
      path: '/api/v1/live-recipe/apply',
      body: {
        revision: 1,
        live_revision: 1,
        current_password: 'fixture-web-password',
        confirm_live: true,
      },
    });
    await expect(page.getByLabel('当前管理员密码', { exact: true })).toHaveValue('');
    await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-web-password');
    await page.getByRole('button', { name: '恢复上一份实盘配方', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
    await expect(
      page.getByText('实盘配方已生效，机器人保持停止。请核对后再手动启动。', { exact: true }),
    ).toBeVisible({ timeout: 15000 });
    await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue('6');
    expect(writes[2]?.path).toBe('/api/v1/live-recipe/rollback');
    expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
      'fixture-web-password',
    );
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: testInfo.outputPath(`live-recipe-${width}.png`),
      fullPage: true,
    });
    await page.getByRole('banner').getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Live configuration and paper comparison', exact: true }),
    ).toBeVisible();
  });
}

test('unconfigured live workspace exposes recipe and research through the separate gateway', async ({
  page,
}) => {
  const { writes, trading } = await workspace(page, false);
  await expect(
    page.getByText('配置 OKX 账户后才能应用。首次配置账户时会使用已保存的实盘草稿。', {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('button', { name: '复制模拟盘生效配方到草稿', exact: true }).click();
  await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue('10');
  await page.getByRole('button', { name: '保存实盘草稿', exact: true }).click();
  await expect(
    page.getByRole('button', { name: '应用到实盘（保持停止）', exact: true }),
  ).toBeDisabled();
  expect(writes).toHaveLength(1);
  const paths: string[] = [];
  await page.route('**/api/v1/research/**', (route) => {
    const path = new URL(route.request().url()).pathname.split('/research/')[1]!;
    paths.push(path);
    const json =
      path === 'strategies'
        ? { strategies: ['NostalgiaForInfinityX8'] }
        : path.startsWith('strategy/')
          ? {
              strategy: 'NostalgiaForInfinityX8',
              timeframe: '5m',
              params: [],
              code: '# fixture X8',
            }
          : path === 'info'
            ? {
                exchange: 'okx',
                trading_mode: 'spot',
                pairs: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
                timeframes: ['5m'],
                stake_currency: 'USDT',
                starting_balance: 10000,
                max_open_trades: 6,
                fee: 0.001,
                preparation: {
                  running: false,
                  status: 'idle',
                  timeframe: null,
                  completed: 0,
                  total: 5,
                  error: null,
                },
              }
            : path === 'backtest/history'
              ? []
              : { running: false, status: 'not_started', status_msg: '', step: '', progress: 0 };
    return route.fulfill({ json });
  });
  await page.getByRole('link', { name: '策略库', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: '策略库', exact: true })).toBeVisible();
  await expect(
    page.getByText('研究使用模拟盘已保存配方与研究策略代码，不会修改或启动实盘交易。', {
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('button', { name: '查看源码', exact: true }).click();
  await expect(page.getByLabel('策略源码', { exact: true })).toHaveValue('# fixture X8');
  await page.getByRole('link', { name: '回测', exact: true }).first().click();
  await expect(page.getByRole('button', { name: '2. 开始回测', exact: true })).toBeVisible();
  expect(paths).toContain('info');
  expect(paths).toContain('strategies');
  expect(paths).toContain('strategy/NostalgiaForInfinityX8');
  expect(
    trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
  ).toEqual([]);
});

test('wrong password clears the secret and an updated draft preserves unsaved edits', async ({
  page,
}) => {
  const { state, writes } = await workspace(page);
  await page.getByLabel('最大持仓数', { exact: true }).fill('8');
  await page.getByRole('heading', { name: '编辑实盘草稿', exact: true }).click();
  await page.getByRole('button', { name: '保存实盘草稿', exact: true }).click();
  await page.getByLabel('当前管理员密码', { exact: true }).fill('wrong-password');
  await page.getByRole('button', { name: '应用到实盘（保持停止）', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '当前密码不正确' })).toBeVisible();
  await expect(page.getByLabel('当前管理员密码', { exact: true })).toHaveValue('');
  expect(state.applied_settings?.max_open_trades).toBe(6);
  await page.getByLabel('最大持仓数', { exact: true }).fill('9');
  await page.getByRole('heading', { name: '编辑实盘草稿', exact: true }).click();
  state.saved.revision += 1;
  await expect(
    page.getByText('实盘配置或草稿已被更新，请重新加载后再操作。', { exact: true }),
  ).toBeVisible({ timeout: 10000 });
  await expect(page.getByLabel('最大持仓数', { exact: true })).toHaveValue('9');
  await expect(page.getByRole('button', { name: '保存实盘草稿', exact: true })).toBeDisabled();
  expect(writes).toHaveLength(2);
});

test('open positions block apply and rollback while draft edits remain available', async ({
  page,
}) => {
  const { state } = await workspace(page);
  state.can_apply = false;
  state.can_rollback = false;
  state.apply_blocker = 'live_recipe_has_positions';
  await expect(
    page.getByText('应用或回滚实盘配方前，请先处理未平仓交易和未完成订单。', { exact: true }),
  ).toBeVisible({ timeout: 10000 });
  await page.getByLabel('最大持仓数', { exact: true }).fill('8');
  await page.getByRole('heading', { name: '编辑实盘草稿', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存实盘草稿', exact: true })).toBeEnabled();
  await page.getByLabel('当前管理员密码', { exact: true }).fill('fixture-web-password');
  await expect(
    page.getByRole('button', { name: '应用到实盘（保持停止）', exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole('button', { name: '恢复上一份实盘配方', exact: true }),
  ).toBeDisabled();
});
