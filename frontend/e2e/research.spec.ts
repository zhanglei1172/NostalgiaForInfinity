import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';

const info = {
  exchange: 'binance',
  trading_mode: 'spot',
  pairs: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'],
  timeframes: ['5m', '15m', '1h', '4h', '1d'],
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
};
const result = {
  strategy_name: 'NostalgiaForInfinityX8',
  stake_currency: 'USDT',
  starting_balance: 10000,
  final_balance: 10450,
  profit_total_abs: 450,
  profit_total: 0.045,
  total_trades: 2,
  pairlist: info.pairs,
  timeframe: '5m',
  backtest_start: '2025-01-01 00:00:00',
  backtest_end: '2025-04-01 00:00:00',
  backtest_start_ts: Date.parse('2025-01-01T00:00:00Z'),
  backtest_end_ts: Date.parse('2025-04-01T00:00:00Z'),
  trades: [
    { close_timestamp: Date.parse('2025-01-31T23:59:00Z'), profit_abs: 1000 },
    { close_timestamp: Date.parse('2025-02-01T00:00:00Z'), profit_abs: -550 },
  ],
};
const ended = {
  status: 'ended',
  running: false,
  status_msg: 'Backtest ended',
  step: 'finished',
  progress: 1,
  backtest_result: { strategy: { NostalgiaForInfinityX8: result } },
};
async function mockResearch(page: Page) {
  const trading = await mockBot(page);
  let started = false;
  let downloaded = false;
  const calls: { endpoint: string; body: unknown }[] = [];
  await page.route('**/api/v1/research/**', async (route) => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname.split('/research/')[1]!;
    if (request.method() === 'POST') calls.push({ endpoint, body: request.postDataJSON() });
    if (endpoint === 'info')
      return route.fulfill({
        json: {
          ...info,
          preparation: downloaded
            ? {
                ...info.preparation,
                status: 'success',
                start_date: '2025-01-01',
                end_date: '2025-04-01',
              }
            : info.preparation,
        },
      });
    if (endpoint === 'strategies')
      return route.fulfill({
        json: { strategies: ['NostalgiaForInfinityX8', 'NostalgiaForInfinityX7'] },
      });
    if (endpoint.startsWith('strategy/'))
      return route.fulfill({
        json: {
          strategy: endpoint.split('/')[1],
          timeframe: '5m',
          params: [],
          code: 'class NostalgiaForInfinityX8:\n    timeframe = "5m"',
        },
      });
    if (endpoint === 'prepare') {
      downloaded = true;
      return route.fulfill({
        json: { ...info.preparation, running: true, status: 'running', timeframe: '5m' },
      });
    }
    if (endpoint === 'backtest/history')
      return route.fulfill({
        json: [
          {
            filename: 'backtest-2025',
            strategy: 'NostalgiaForInfinityX8',
            run_id: 'fixture',
            backtest_start_time: 1735689600,
          },
        ],
      });
    if (endpoint === 'backtest/history/result') return route.fulfill({ json: ended });
    if (endpoint === 'backtest' && request.method() === 'POST') {
      started = true;
      return route.fulfill({
        json: {
          status: 'running',
          running: true,
          status_msg: 'Backtest started',
          step: 'analyze',
          progress: 0.1,
        },
      });
    }
    if (endpoint === 'backtest')
      return route.fulfill({
        json: started
          ? ended
          : {
              status: 'not_started',
              running: false,
              status_msg: 'Backtest not yet executed',
              step: '',
              progress: 0,
            },
      });
    return route.fulfill({ status: 404, json: { detail: 'Not found' } });
  });
  await login(page);
  return { trading, calls };
}

test('paper bot navigation exposes research and strategy source without changing the trading strategy', async ({
  page,
}) => {
  const { trading } = await mockResearch(page);
  await page.getByRole('link', { name: '策略库', exact: true }).first().click();
  await expect(
    page.getByRole('heading', { name: 'NostalgiaForInfinityX8', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '查看源码', exact: true }).click();
  await expect(page.getByLabel('策略源码')).toHaveAttribute('readonly', '');
  await expect(page.getByLabel('策略源码')).toHaveValue(/class NostalgiaForInfinityX8/);
  await page.getByRole('link', { name: '使用此策略回测' }).click();
  await expect(page.getByRole('heading', { name: '回测', exact: true })).toBeVisible();
  await expect(
    page.getByText('测试币对: BTC/USDT, ETH/USDT, SOL/USDT', { exact: true }),
  ).toBeVisible();
  expect(trading.some((r) => /reload|forceenter|start|stop/.test(r.endpoint))).toBe(false);
});

test('download and backtest use the research service and monthly returns export correctly', async ({
  page,
}) => {
  const { calls, trading } = await mockResearch(page);
  await page.goto('/backtest');
  await page.getByLabel('开始日期（UTC）', { exact: true }).fill('2025-01-01');
  await page.getByLabel('结束日期（不含当天，UTC）', { exact: true }).fill('2025-04-01');
  await page.getByRole('button', { name: '1. 下载历史行情' }).click();
  await expect(page.getByText('历史行情已准备好，可以开始回测。', { exact: true })).toBeVisible({
    timeout: 10000,
  });
  expect(calls[0]).toEqual({
    endpoint: 'prepare',
    body: { start_date: '2025-01-01', end_date: '2025-04-01' },
  });
  await page.getByRole('button', { name: '2. 开始回测' }).click();
  await expect(page.getByRole('heading', { name: '每月回测收益', exact: true })).toBeVisible({
    timeout: 10000,
  });
  const january = page.getByRole('row').filter({ hasText: '2025-01' });
  const february = page.getByRole('row').filter({ hasText: '2025-02' });
  await expect(january).toContainText('1,000.00');
  await expect(january).toContainText('10.00%');
  await expect(february).toContainText('-550.00');
  await expect(february).toContainText('-5.00%');
  await expect(page.getByRole('row').filter({ hasText: '2025-03' })).toContainText('0.00%');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出月度 CSV' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('monthly-NostalgiaForInfinityX8.csv');
  const stream = await file.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(chunk);
  const csv = Buffer.concat(chunks).toString('utf8');
  expect(csv).toContain('"2025-02","-550.00000000","-5.0000%"');
  expect(calls.find((r) => r.endpoint === 'backtest')?.body).toMatchObject({
    strategy: 'NostalgiaForInfinityX8',
    timerange: '20250101-20250401',
    dry_run_wallet: 10000,
  });
  expect(trading.filter((r) => !['token/login', 'pair_candles'].includes(r.endpoint))).toEqual([]);
});

test('saved results restore after reload and research pages fit mobile screens', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockResearch(page);
  await page.goto('/backtest');
  await page.getByRole('button', { name: '已保存的回测结果', exact: true }).click();
  await page.getByRole('option').first().click();
  await expect(page.getByRole('heading', { name: '每月回测收益', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('research-mobile.png'), fullPage: true });
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Backtesting', exact: true })).toBeVisible();
});

test('missing research service shows a recoverable error', async ({ page }) => {
  await mockResearch(page);
  await page.route('**/api/v1/research/strategies', (route) =>
    route.fulfill({ status: 503, json: { detail: 'research_service_unavailable' } }),
  );
  await page.goto('/backtest');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '2. 开始回测' })).toHaveCount(0);
});

test('incomplete recipe candles prompt a download before backtesting', async ({ page }) => {
  await mockResearch(page);
  await page.route('**/api/v1/research/backtest', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 409, json: { detail: 'research_data_required' } })
      : route.fallback(),
  );
  await page.goto('/backtest');
  await page.getByRole('button', { name: '2. 开始回测', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('请先下载所选全部币对及日期范围的历史行情');
  await expect(page.getByRole('button', { name: '1. 下载历史行情', exact: true })).toBeEnabled();
});
