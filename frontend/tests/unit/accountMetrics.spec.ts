import { describe, expect, it } from 'vitest';
import {
  accountMetrics,
  historyPoints,
  readObservations,
  addObservation,
  observationKey,
} from '@/utils/accountMetrics';

describe('account valuations', () => {
  it('uses the bot valuation without adding open P&L a second time', () => {
    expect(
      accountMetrics(
        { total: 15000, total_bot: 10230, starting_capital: 10000 },
        { profit_closed_coin: 200, profit_all_coin: 230 },
      ),
    ).toMatchObject({
      equity: 10230,
      totalProfit: 230,
      realized: 200,
      unrealized: 30,
      changePercent: 2.3,
    });
  });
  it('preserves zero balances, losses and unavailable values', () => {
    expect(accountMetrics({ total_bot: 0, total: 100, starting_capital: 100 })).toMatchObject({
      equity: 0,
      totalProfit: -100,
      changePercent: -100,
    });
    expect(accountMetrics({}).equity).toBeUndefined();
    expect(accountMetrics({ total: Number.NaN }).totalProfit).toBeUndefined();
    expect(accountMetrics({ total: 12, starting_capital: 0 }).changePercent).toBeUndefined();
  });
  it('maps server columns, deduplicates timestamps, rejects nulls and sorts history', () => {
    expect(
      historyPoints({
        columns: ['total_quote', '__date_ts'],
        length: 5,
        data: [
          [30, 2000],
          [10, 1000],
          [31, 2000],
          [null as never, 3000],
          [22, 'bad'],
        ],
      }),
    ).toEqual([
      { time: 1000, value: 10 },
      { time: 2000, value: 31 },
    ]);
    expect(historyPoints({ columns: [], length: 1, data: [[1, 2]] })).toEqual([]);
  });
  it('bounds stored observations and handles malformed or expired storage', () => {
    const now = 40 * 86400000;
    expect(readObservations('invalid', now)).toEqual([]);
    expect(
      readObservations(
        JSON.stringify([
          { time: now + 1, value: 12 },
          { time: 1, value: 12 },
          { time: now - 100, value: null },
          { time: now, value: 0 },
        ]),
        now,
      ),
    ).toEqual([{ time: now, value: 0 }]);
  });
  it('keeps the newest sample per five minutes and partitions account identities', () => {
    expect(
      addObservation(
        [
          { time: 600001, value: 100 },
          { time: 300001, value: 99 },
        ],
        { time: 600002, value: 101 },
      ),
    ).toEqual([
      { time: 300001, value: 99 },
      { time: 600002, value: 101 },
    ]);
    expect(observationKey('bot-1 USDT dry')).not.toBe(observationKey('bot-1 USDT live'));
    expect(observationKey('http://user:secret@local')).not.toContain('secret');
  });
});
