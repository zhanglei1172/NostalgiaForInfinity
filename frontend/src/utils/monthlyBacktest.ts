import type { StrategyBacktestResult } from '@/types';

export interface MonthlyBacktestRow {
  month: string;
  profit: number;
  openingBalance: number;
  closingBalance: number;
  returnRatio: number | null;
  trades: number;
  wins: number;
  losses: number;
  partial: boolean;
}

export function monthlyBacktest(result: StrategyBacktestResult): MonthlyBacktestRow[] {
  const toMs = (value: number) => (value < 1e12 ? value * 1000 : value);
  const start = toMs(result.backtest_start_ts);
  const end = toMs(result.backtest_end_ts);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return [];
  const rows: MonthlyBacktestRow[] = [];
  const cursor = new Date(start);
  cursor.setUTCDate(1);
  cursor.setUTCHours(0, 0, 0, 0);
  // Include the final candle when the engine reports its opening timestamp.
  const match = /^(\d+)([mhd])$/.exec(result.timeframe);
  const candleMs = match
    ? Number(match[1]) * ({ m: 60, h: 3600, d: 86400 }[match[2]!] ?? 0) * 1000
    : 0;
  const until = end % 86400000 === 0 ? end : end + candleMs;
  while (cursor.getTime() < until && rows.length < 1200) {
    const monthStart = cursor.getTime();
    const month = cursor.toISOString().slice(0, 7);
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    rows.push({
      month,
      profit: 0,
      openingBalance: 0,
      closingBalance: 0,
      returnRatio: null,
      trades: 0,
      wins: 0,
      losses: 0,
      partial: start > monthStart || until < cursor.getTime(),
    });
  }
  const indexed = new Map(rows.map((row) => [row.month, row]));
  for (const trade of result.trades) {
    const timestamp = trade.close_timestamp;
    if (
      timestamp == null ||
      typeof trade.profit_abs !== 'number' ||
      !Number.isFinite(trade.profit_abs)
    )
      continue;
    const month = new Date(toMs(timestamp)).toISOString().slice(0, 7);
    const row = indexed.get(month);
    if (!row) continue;
    row.profit += trade.profit_abs;
    row.trades++;
    if (trade.profit_abs > 0) row.wins++;
    if (trade.profit_abs < 0) row.losses++;
  }
  let balance = result.starting_balance;
  for (const row of rows) {
    row.openingBalance = balance;
    row.returnRatio = balance > 0 ? row.profit / balance : null;
    balance += row.profit;
    row.closingBalance = balance;
  }
  return rows;
}
