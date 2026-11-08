import { expect, test, type Page } from '@playwright/test';
import { login, mockBot } from './helpers';

const day = 86400000;
const start = Date.parse('2025-01-01T00:00:00Z');
const result = {
  strategy_name: 'NostalgiaForInfinityX8',
  stake_currency: 'USDT',
  starting_balance: 10000,
  final_balance: 13000,
  profit_total_abs: 3000,
  profit_total: 0.3,
  total_trades: 3,
  pairlist: ['BTC/USDT'],
  timeframe: '5m',
  backtest_start: '2025-01-01 00:00:00',
  backtest_end: '2025-01-11 00:00:00',
  backtest_start_ts: start,
  backtest_end_ts: start + 10 * day,
  trades: [
    { close_timestamp: start + day, profit_abs: 2000 },
    { close_timestamp: start + 2 * day, profit_abs: -3000 },
    { close_timestamp: start + 5 * day, profit_abs: 4000 },
  ],
};
function wallet(values = [10000, 12000, 9000, 10000, 12000, 13000]) {
  return {
    columns: ['__date_ts', 'total_quote'],
    data: values.map((balance, index) => [start + index * day, balance]),
    length: values.length,
  };
}
async function workspace(
  page: Page,
  options: { values?: number[]; summary?: boolean; latest?: boolean } = {},
) {
  const trading = await mockBot(page);
  let walletAvailable = !options.summary;
  const requests: string[] = [];
  const summary = {
    max_drawdown_abs: 400,
    max_drawdown_account: 0.04,
    max_relative_drawdown: 0.05,
    drawdown_duration_s: 7200,
  };
  await page.route('**/api/v1/research/**', (route) => {
    const endpoint = new URL(route.request().url()).pathname.split('/research/')[1]!;
    requests.push(endpoint);
    if (endpoint.endsWith('/wallet'))
      return walletAvailable
        ? route.fulfill({ json: wallet(options.values) })
        : route.fulfill({ status: 404, json: { detail: 'No wallet history' } });
    if (endpoint === 'strategies')
      return route.fulfill({ json: { strategies: ['NostalgiaForInfinityX8'] } });
    if (endpoint === 'info')
      return route.fulfill({
        json: {
          exchange: 'okx',
          pairs: ['BTC/USDT'],
          max_open_trades: 6,
          stake_currency: 'USDT',
          fee: 0.001,
          preparation: { running: false, status: 'idle', completed: 0, total: 5 },
        },
      });
    if (endpoint === 'backtest/history')
      return route.fulfill({
        json: [
          {
            filename: 'risk-fixture',
            strategy: 'NostalgiaForInfinityX8',
            run_id: 'risk',
            backtest_start_time: start / 1000,
          },
        ],
      });
    if (endpoint === 'backtest/history/result' || (options.latest && endpoint === 'backtest'))
      return route.fulfill({
        json: {
          running: false,
          status: 'ended',
          backtest_result: {
            metadata: options.latest
              ? { NostalgiaForInfinityX8: { filename: 'risk-fixture' } }
              : {},
            strategy: {
              NostalgiaForInfinityX8: {
                ...result,
                ...(options.summary ? { wallet_stats: summary } : {}),
              },
            },
          },
        },
      });
    return route.fulfill({ json: { running: false, status: 'not_started' } });
  });
  await login(page);
  await page.goto('/backtest');
  if (!options.latest) {
    await page.getByRole('button', { name: '已保存的回测结果', exact: true }).click();
    await page.getByRole('option').first().click();
  }
  const report = page.getByRole('region', { name: '回撤与修复', exact: true });
  await expect(report).toBeVisible();
  await expect(report.getByText('正在加载钱包记录以分析回撤…', { exact: true })).toHaveCount(0);
  return {
    report,
    trading,
    requests,
    restoreWallet: () => {
      walletAvailable = true;
    },
  };
}

for (const width of [1440, 390]) {
  test(`wallet drawdown reports recovery separately from decline at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const { report, trading, requests } = await workspace(page);
    await expect(report.getByText('计算口径: 钱包估值采样', { exact: true })).toBeVisible();
    await expect(report.getByText('25.00%', { exact: true })).toBeVisible();
    const recovery = report.locator('.risk-metrics > div').filter({ hasText: '最大回撤修复时间' });
    await expect(recovery).toContainText('3 天 0 小时 0 分钟');
    const decline = report.locator('.risk-details > div').filter({ hasText: '下跌持续时间' });
    await expect(decline).toContainText('1 天 0 小时 0 分钟');
    await expect(report.getByText('2025-01-05 00:00:00 UTC', { exact: true })).toBeVisible();
    await expect(report.getByLabel('回测回撤曲线', { exact: true })).toBeVisible();
    expect(requests).toContain('backtest/history/risk-fixture/NostalgiaForInfinityX8/wallet');
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await report.getByRole('heading').scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`drawdown-${width}.png`) });
    await page.getByRole('banner').getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Drawdown and recovery', exact: true }),
    ).toBeVisible();
  });
}

test('newly finished backtests use the archive filename returned in metadata', async ({ page }) => {
  const { report, requests } = await workspace(page, { latest: true });
  await expect(report.getByText('25.00%', { exact: true })).toBeVisible();
  expect(requests).toContain('backtest/history/risk-fixture/NostalgiaForInfinityX8/wallet');
});

test('an unrecovered drawdown is measured through the test end', async ({ page }) => {
  const { report } = await workspace(page, { values: [10000, 12000, 9000, 11000] });
  const recovery = report.locator('.risk-metrics > div').filter({ hasText: '最大回撤修复时间' });
  await expect(recovery).toContainText('截至回测结束仍未修复');
  await expect(recovery).toContainText('9 天 0 小时 0 分钟');
  const longest = report.locator('.risk-metrics > div').filter({ hasText: '最长水下时间' });
  await expect(longest).toContainText('9 天 0 小时 0 分钟');
  await expect(longest).toContainText('截至回测结束仍处于水下');
});

test('summary-only results do not invent recovery and wallet failures can be retried', async ({
  page,
}) => {
  const { report, restoreWallet } = await workspace(page, { summary: true });
  await expect(report.getByText('5.00%', { exact: true })).toBeVisible();
  const recovery = report.locator('.risk-metrics > div').filter({ hasText: '最大回撤修复时间' });
  await expect(recovery).toContainText('暂无数据');
  await expect(report.getByLabel('回测回撤曲线', { exact: true })).toHaveCount(0);
  restoreWallet();
  await report.getByRole('button', { name: '重试加载钱包记录', exact: true }).click();
  await expect(report.getByText('25.00%', { exact: true })).toBeVisible();
  await expect(recovery).toContainText('3 天 0 小时 0 分钟');
});
