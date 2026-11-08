import { describe, expect, it } from 'vitest';
import type { StrategyBacktestResult } from '@/types';
import { monthlyBacktest } from '@/utils/monthlyBacktest';

function result(overrides: Record<string, unknown> = {}) {
  return {
    backtest_start_ts: Date.parse('2025-01-01T00:00:00Z'),
    backtest_end_ts: Date.parse('2025-04-01T00:00:00Z'),
    timeframe: '5m',
    starting_balance: 10000,
    trades: [
      { close_timestamp: Date.parse('2025-01-31T23:59:00Z'), profit_abs: 1000 },
      { close_timestamp: Date.parse('2025-02-01T00:00:00Z'), profit_abs: -550 },
    ],
    ...overrides,
  } as unknown as StrategyBacktestResult;
}
describe('monthly backtest accounting', () => {
  it('groups by UTC close month, includes empty months and calculates returns on opening realized capital', () => {
    const rows = monthlyBacktest(result());
    expect(rows.map((row) => row.month)).toEqual(['2025-01', '2025-02', '2025-03']);
    expect(rows.map((row) => row.profit)).toEqual([1000, -550, 0]);
    expect(rows.map((row) => row.returnRatio)).toEqual([0.1, -0.05, 0]);
    expect(rows.map((row) => row.closingBalance)).toEqual([11000, 10450, 10450]);
    expect(rows.map((row) => row.trades)).toEqual([1, 1, 0]);
    expect(rows.every((row) => !row.partial)).toBe(true);
  });
  it('marks partial periods and avoids a fabricated return when capital is exhausted', () => {
    const rows = monthlyBacktest(
      result({
        backtest_start_ts: Date.parse('2025-01-15T00:00:00Z'),
        backtest_end_ts: Date.parse('2025-03-15T12:00:00Z'),
        starting_balance: 0,
        trades: [],
      }),
    );
    expect(rows.map((row) => row.partial)).toEqual([true, false, true]);
    expect(rows.every((row) => row.returnRatio === null)).toBe(true);
  });
  it('treats a last 5m candle at month end as a complete month', () => {
    const rows = monthlyBacktest(result({ backtest_end_ts: Date.parse('2025-03-31T23:55:00Z') }));
    expect(rows).toHaveLength(3);
    expect(rows[2]?.partial).toBe(false);
  });
  it('accepts older second timestamps and rejects invalid date ranges', () => {
    const rows = monthlyBacktest(
      result({ backtest_start_ts: Date.parse('2025-01-01T00:00:00Z') / 1000 }),
    );
    expect(rows[0]?.profit).toBe(1000);
    expect(monthlyBacktest(result({ backtest_end_ts: NaN }))).toEqual([]);
  });
});
