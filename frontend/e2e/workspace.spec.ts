import { expect, test, type Page } from '@playwright/test';
import { mockBot, login } from './helpers';

async function accountScenario(page: Page, history: 'normal' | 'empty' | 'error' = 'normal') {
  const requests = await mockBot(page);
  const now = Date.now();
  await page.route('**/api/v1/balance', (route) =>
    route.fulfill({
      json: {
        currencies: [],
        total: 12471.26,
        total_bot: 12471.26,
        stake: 'USDT',
        starting_capital: 12000,
      },
    }),
  );
  await page.route('**/api/v1/profit*', (route) => {
    const profit = {
      profit_closed_coin: 471.26,
      profit_all_coin: 471.26,
      closed_trade_count: 18,
      winning_trades: 12,
      losing_trades: 6,
      trade_count: 18,
    };
    return route.fulfill({
      json: route.request().url().endsWith('profit_all') ? { all: profit } : profit,
    });
  });
  await page.route('**/api/v1/historic_balance', (route) =>
    route.fulfill(
      history === 'error'
        ? { status: 503, json: { detail: 'History unavailable' } }
        : {
            json: {
              columns: ['__date_ts', 'total_quote'],
              length: history === 'empty' ? 0 : 30,
              capture_start_ts: now - 15 * 86400000,
              data:
                history === 'empty'
                  ? []
                  : Array.from({ length: 30 }, (_, i) => [
                      now - (29 - i) * 86400000,
                      Math.round((12000 + i * 16 + Math.sin(i / 2) * 30) * 100) / 100,
                    ]),
            },
          },
    ),
  );
  await page.route('**/api/v1/daily**', (route) =>
    route.fulfill({
      json: {
        stake_currency: 'USDT',
        fiat_display_currency: 'USD',
        data: Array.from({ length: 7 }, (_, i) => ({
          date: new Date(now - i * 86400000).toISOString().slice(0, 10),
          abs_profit: 12 + i * 2,
          starting_balance: 12000,
          trade_count: 2,
          rel_profit: 0.001,
          fiat_value: 12 + i * 2,
        })),
      },
    }),
  );
  await login(page);
  await page.goto('/dashboard');
  await expect(page.getByTestId('equity-value')).toContainText('12,471.26');
  return requests;
}

test('dashboard shows honest equity history, range controls, storage and bilingual labels', async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const requests = await accountScenario(page);
  await expect(page.getByTestId('equity-panel').locator('canvas')).toBeVisible();
  await expect(
    page.getByText('当前空仓不代表策略已经出现入场信号。', { exact: false }),
  ).toBeVisible();
  await page.getByText('查看图表数据', { exact: false }).click();
  const table = page.getByTestId('equity-panel').getByRole('table');
  await expect(table.getByRole('row')).toHaveCount(32); // Header, 30 daily records, one observation.
  await page.getByRole('combobox', { name: '图表时间范围' }).click();
  await page.getByRole('option', { name: '近 7 天', exact: true }).click();
  await expect(table.getByRole('row')).toHaveCount(9); // Seven days ago has elapsed; never invent range-boundary points.
  await page.getByRole('combobox', { name: '图表时间范围' }).click();
  await page.getByRole('option', { name: '全部记录', exact: true }).click();
  await page.getByText('查看图表数据', { exact: false }).click();
  await page.evaluate(() => {
    const key = Object.keys(localStorage).find((k) => k.startsWith('nfi-equity-v1-'))!;
    const now = Date.now();
    localStorage.setItem(
      key,
      JSON.stringify(
        Array.from({ length: 36 }, (_, i) => ({
          time: now - (36 - i) * 300000,
          value: 12440 + i * 0.9 + Math.sin(i / 3) * 5,
        })),
      ),
    );
  });
  await page.reload();
  await expect(page.getByTestId('equity-panel').locator('canvas')).toBeVisible();
  await expect(page.locator('.workspace-sidebar svg').first()).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.screenshot({ path: testInfo.outputPath('dashboard-desktop.png') });
  await page.getByRole('combobox', { name: '界面语言' }).click();
  await page.getByRole('option', { name: 'English', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Account equity over time', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Toggle Night Mode' }).click();
  await expect(page.locator('html')).not.toHaveClass(/dark/);
  await page.screenshot({ path: testInfo.outputPath('dashboard-light.png') });
  expect(errors).toEqual([]);
  expect(
    requests.filter((r) => ['stop', 'forcebuy', 'forceexit', 'start'].includes(r.endpoint)),
  ).toEqual([]);
});

test('daily history failure is visible while refresh recovers without losing observations', async ({
  page,
}) => {
  await accountScenario(page, 'error');
  await expect(page.getByText('每日历史加载失败，请刷新重试；已有观测记录仍保留。')).toBeVisible();
  await page.route('**/api/v1/historic_balance', (route) =>
    route.fulfill({ json: { columns: ['__date_ts', 'total_quote'], data: [], length: 0 } }),
  );
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByText('每日历史加载失败，请刷新重试；已有观测记录仍保留。')).toHaveCount(0);
  await page.getByText('查看图表数据', { exact: false }).click();
  await expect(page.getByTestId('equity-panel').getByRole('table').getByRole('row')).toHaveCount(2);
});

test('mobile navigation, chart and trading controls fit the viewport', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await accountScenario(page, 'empty');
  await page.screenshot({ path: testInfo.outputPath('dashboard-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('navigation', { name: '快捷导航' })).toBeInViewport();
  await page
    .getByRole('navigation', { name: '快捷导航' })
    .getByRole('link', { name: '交易', exact: true })
    .click();
  await expect(page.getByRole('button', { name: '暂停开仓', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('trade-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '打开导航', exact: true }).click();
  await page.getByRole('dialog').getByRole('link', { name: '日志', exact: true }).click();
  await expect(page.getByRole('heading', { name: '日志', exact: true })).toBeVisible();
});

test('logs support search and severity filters, and settings remain accessible', async ({
  page,
}, testInfo) => {
  await accountScenario(page);
  await page.goto('/logs');
  await page.getByRole('textbox', { name: '搜索日志' }).fill('no such log record');
  await expect(page.getByText('没有匹配的日志', { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索日志' }).fill('');
  await page.getByRole('combobox', { name: '日志级别' }).click();
  await page.getByRole('option', { name: 'ERROR', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('logs-desktop.png') });
  await page.goto('/balance');
  await expect(page.getByRole('heading', { name: '余额', exact: true })).toBeVisible();
  await page.goto('/trade_history');
  await expect(page.getByRole('columnheader', { name: '交易对', exact: true })).toBeVisible();
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: '设置', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '界面语言' }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('settings-desktop.png') });
});

test('failed balance refresh keeps the last observation and zero remains a valid equity', async ({
  page,
}) => {
  await accountScenario(page, 'empty');
  await page.route('**/api/v1/balance', (route) =>
    route.fulfill({ status: 503, json: { detail: 'Balance unavailable' } }),
  );
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByText('部分账户数据未能刷新', { exact: true })).toBeVisible();
  await expect(page.getByTestId('equity-value')).toContainText('12,471.26');
  await page.route('**/api/v1/balance', (route) =>
    route.fulfill({
      json: { currencies: [], stake: 'USDT', total: 0, total_bot: 0, starting_capital: 12000 },
    }),
  );
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByTestId('equity-value')).toHaveText('0.00USDT');
  await expect(page.getByText('部分账户数据未能刷新', { exact: true })).toHaveCount(0);
});
