import { expect, test } from '@playwright/test';
import { login, mockBot } from './helpers';
import type { StrategyActivity } from '../src/types/activity';

const snapshot: StrategyActivity = {
  as_of: '2026-11-08T02:00:00Z',
  exchange: 'okx',
  dry_run: true,
  state: 'stopped',
  strategy: 'NostalgiaForInfinityX8',
  timeframe: '5m',
  open_trades: 0,
  free_slots: 6,
  pair_count: 2,
  reasons: ['stopped'],
  journal_since: '2026-11-08T01:00:00Z',
  pairs: [
    {
      pair: 'BTC/USDT',
      candle_at: null,
      analyzed_at: null,
      signal: 'unavailable',
      entry_tag: null,
      exit_tag: null,
      lock_until: null,
      reasons: ['stopped', 'no_analysis'],
    },
    {
      pair: 'ETH/USDT',
      candle_at: '2026-11-08T01:55:00Z',
      analyzed_at: '2026-11-08T02:00:00Z',
      signal: 'entry',
      entry_tag: '120',
      exit_tag: null,
      lock_until: null,
      reasons: ['stopped', 'entry_candidate'],
    },
  ],
  fills: [
    {
      trade_id: 7,
      pair: 'SOL/USDT',
      side: 'sell',
      at: '2026-11-08T01:00:00Z',
      filled: 0.1,
      price: 150,
      order_open: false,
      tag: 'partial-reduction',
      exit_reason: null,
    },
  ],
  rejections: [{ at: '2026-11-08T01:30:00Z', pair: 'XRP/USDT', reason: 'slippage' }],
};

for (const width of [1440, 390]) {
  test(`strategy activity explains stopped state, signals and fills at ${width}px without trading`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    const trading = await mockBot(page);
    const reads: string[] = [];
    await page.route('**/api/v1/strategy-activity', async (route) => {
      reads.push(route.request().method());
      return route.fulfill({ json: snapshot });
    });
    await login(page);
    await page.goto('/dashboard');
    await page.locator('main').getByRole('link', { name: '策略动态', exact: true }).click();
    await expect(page.getByRole('heading', { name: '策略动态', exact: true })).toBeVisible();
    await expect(
      page.getByText('机器人已停止：点击启动后才会分析策略并管理持仓。').first(),
    ).toBeVisible();
    await expect(page.getByText('尚无分析完成的 K 线缓存；启动后需等待行情预热。')).toBeVisible();
    await expect(page.getByText('NFI 拒绝开仓：开仓报价超过滑点容忍度。')).toBeVisible();
    await expect(page.getByText('partial-reduction', { exact: true })).toBeVisible();
    await expect(page.getByText('最终退出原因', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '刷新', exact: true }).click();
    await expect.poll(() => reads.length).toBeGreaterThan(1);
    expect(reads.every((method) => method === 'GET')).toBe(true);
    await page.getByLabel('筛选币对', { exact: true }).fill('ETH');
    await expect(page.getByText('BTC/USDT', { exact: true })).toHaveCount(0);
    await expect(page.getByText('ETH/USDT', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath(`activity-${width}.png`), fullPage: true });
    await page.getByRole('combobox', { name: '界面语言' }).click();
    await page.getByRole('option', { name: 'English', exact: true }).click();
    await expect(
      page.getByRole('heading', { name: 'Strategy activity', exact: true }),
    ).toBeVisible();
    expect(
      trading.filter(({ endpoint }) => !['token/login', 'pair_candles'].includes(endpoint)),
    ).toEqual([]);
  });
}

test('failed refresh visibly marks retained strategy observations as stale', async ({ page }) => {
  await mockBot(page);
  let failed = false;
  await page.route('**/api/v1/strategy-activity', (route) =>
    failed
      ? route.fulfill({ status: 503, json: { detail: 'unavailable' } })
      : route.fulfill({ json: snapshot }),
  );
  await login(page);
  await page.goto('/activity');
  await expect(page.getByText('partial-reduction', { exact: true })).toBeVisible();
  failed = true;
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('策略动态刷新失败');
  await expect(page.getByText('partial-reduction', { exact: true })).toBeVisible();
});
