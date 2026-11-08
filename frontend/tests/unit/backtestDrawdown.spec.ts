import { describe, expect, it } from 'vitest';
import type { StrategyBacktestResult, WalletHistory } from '@/types';
import { backtestDrawdown } from '@/utils/backtestDrawdown';

const start = Date.parse('2025-01-01T00:00:00Z');
const day = 86400000;
function result(overrides: Record<string, unknown> = {}) {
  return {
    starting_balance: 100,
    backtest_start_ts: start,
    backtest_end_ts: start + 10 * day,
    trades: [],
    total_trades: 0,
    ...overrides,
  } as unknown as StrategyBacktestResult;
}
function wallet(values: [number, number][]): WalletHistory {
  return {
    columns: ['__date_ts', 'total_quote'],
    data: values.map(([offset, balance]) => [start + offset * day, balance]),
    length: values.length,
  };
}

describe('backtest drawdown and recovery accounting', () => {
  it('distinguishes peak-to-trough decline from peak-to-recovery time', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [0, 100],
        [1, 120],
        [2, 90],
        [3, 100],
        [4, 120],
        [5, 130],
      ]),
    );
    expect(risk.source).toBe('wallet');
    expect(risk.maxRatio).toBe(0.25);
    expect(risk.maxAmount).toBe(30);
    expect(risk.maximum).toMatchObject({
      peak: start + day,
      trough: start + 2 * day,
      recovered: start + 4 * day,
    });
    expect(risk.longestMs).toBe(3 * day);
  });
  it('keeps an unrecovered drawdown open until test end instead of inventing a recovery', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [0, 100],
        [1, 120],
        [2, 90],
        [3, 100],
      ]),
    );
    expect(risk.maximum?.recovered).toBeNull();
    expect(risk.longestMs).toBe(9 * day);
    expect(risk.points.at(-1)?.timestamp).toBe(start + 10 * day);
    expect(risk.points.at(-1)?.ratio).toBeCloseTo(1 / 6);
  });
  it('includes the starting capital when the first saved sample is already a loss', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [1, 90],
        [2, 100],
      ]),
    );
    expect(risk.maxRatio).toBe(0.1);
    expect(risk.maximum?.peak).toBe(start);
    expect(risk.maximum?.recovered).toBe(start + 2 * day);
  });
  it('starts the clock at the last equal high before the decline', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [0, 100],
        [1, 120],
        [2, 120],
        [3, 90],
        [4, 120],
      ]),
    );
    expect(risk.maximum?.peak).toBe(start + 2 * day);
    expect(risk.longestMs).toBe(2 * day);
  });
  it('keeps maximum percentage, maximum money and longest underwater episodes distinct', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [0, 100],
        [1, 120],
        [2, 90],
        [3, 120],
        [4, 200],
        [5, 160],
      ]),
    );
    expect(risk.maxRatio).toBe(0.25);
    expect(risk.maxAmount).toBe(40);
    expect(risk.maximum?.amount).toBe(30);
    expect(risk.maximum?.recovered).toBe(start + 3 * day);
    expect(risk.longest?.peak).toBe(start + 4 * day);
    expect(risk.longest?.recovered).toBeNull();
    expect(risk.longestMs).toBe(6 * day);
  });
  it('uses wallet valuations even when final NFI trade profits never show a loss', () => {
    const r = result({
      total_trades: 1,
      trades: [{ close_timestamp: start + 5 * day, profit_abs: 30 }],
    });
    const risk = backtestDrawdown(
      r,
      wallet([
        [0, 100],
        [1, 80],
        [5, 130],
      ]),
    );
    expect(risk.maxRatio).toBe(0.2);
    expect(backtestDrawdown(r).maxRatio).toBe(0);
  });
  it('combines simultaneous closes before calculating a realized high-water mark', () => {
    const r = result({
      total_trades: 2,
      trades: [
        { close_timestamp: start + day, profit_abs: 100 },
        { close_timestamp: start + day, profit_abs: -100 },
      ],
    });
    expect(backtestDrawdown(r).maxRatio).toBe(0);
    expect(backtestDrawdown(r).maximum).toBeNull();
  });
  it('uses engine wallet summaries when samples are absent without fabricating recovery dates', () => {
    const risk = backtestDrawdown(
      result({
        wallet_stats: {
          max_drawdown_abs: 30,
          max_drawdown_account: 0.2,
          max_relative_drawdown: 0.25,
          drawdown_duration_s: 7200,
        },
      }),
    );
    expect(risk.source).toBe('wallet_summary');
    expect(risk.maxRatio).toBe(0.25);
    expect(risk.maximum).toBeNull();
    expect(risk.longestMs).toBeNull();
  });
  it('reports zero without a fictitious episode for monotonically rising or empty results', () => {
    for (const risk of [
      backtestDrawdown(result()),
      backtestDrawdown(
        result(),
        wallet([
          [0, 100],
          [1, 110],
          [2, 120],
        ]),
      ),
    ]) {
      expect(risk.maxRatio).toBe(0);
      expect(risk.maxAmount).toBe(0);
      expect(risk.maximum).toBeNull();
      expect(risk.longestMs).toBe(0);
    }
  });
  it('accepts unsorted historical second timestamps', () => {
    const curve = wallet([
      [2, 80],
      [0, 100],
      [4, 100],
    ]);
    curve.data = curve.data.map(([timestamp, balance]) => [Number(timestamp) / 1000, balance!]);
    const risk = backtestDrawdown(result({ backtest_start_ts: start / 1000 }), curve);
    expect(risk.maxRatio).toBe(0.2);
    expect(risk.maximum?.recovered).toBe(start + 4 * day);
  });
  it('does not turn incomplete or invalid result data into a zero-risk report', () => {
    expect(backtestDrawdown(result({ total_trades: 2 })).source).toBe('unavailable');
    expect(backtestDrawdown(result({ starting_balance: 0 })).source).toBe('unavailable');
    expect(backtestDrawdown(result({ backtest_end_ts: NaN })).source).toBe('unavailable');
    expect(
      backtestDrawdown(
        result(),
        wallet([
          [0, 100],
          [11, 50],
        ]),
      ).source,
    ).toBe('unavailable');
    const malformed = wallet([
      [0, 100],
      [1, NaN],
    ]);
    const r = result({ wallet_stats: { max_drawdown_abs: 30, max_drawdown_account: 0.2 } });
    expect(backtestDrawdown(r, malformed).source).toBe('wallet_summary');
  });
  it('ignores floating point dust when detecting a recovery', () => {
    const risk = backtestDrawdown(
      result(),
      wallet([
        [0, 100],
        [1, 90],
        [2, 99.9999999999],
      ]),
    );
    expect(risk.maximum?.recovered).toBe(start + 2 * day);
    expect(risk.points.at(-1)?.ratio).toBe(0);
  });
});
