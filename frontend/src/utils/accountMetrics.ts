import type { BalanceInterface, ProfitStats, WalletHistory } from '@/types';

export interface AccountPoint {
  time: number;
  value: number;
}
export function finiteValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}
export function accountMetrics(balance: Partial<BalanceInterface>, profit?: Partial<ProfitStats>) {
  const equity = finiteValue(balance.total_bot) ?? finiteValue(balance.total);
  const initial = finiteValue(balance.starting_capital);
  const realized = finiteValue(profit?.profit_closed_coin);
  const totalProfit = equity !== undefined && initial !== undefined ? equity - initial : undefined;
  return {
    equity,
    initial,
    realized,
    totalProfit,
    // This is a change in account value, including deposits/withdrawals, not a trading return.
    changePercent:
      totalProfit !== undefined && initial !== undefined && initial > 0
        ? (totalProfit / initial) * 100
        : undefined,
    unrealized:
      finiteValue(profit?.profit_all_coin) !== undefined && realized !== undefined
        ? profit!.profit_all_coin! - realized
        : undefined,
    winRate: profit?.closed_trade_count
      ? ((profit.winning_trades ?? 0) / profit.closed_trade_count) * 100
      : undefined,
  };
}
export function historyPoints(history?: WalletHistory): AccountPoint[] {
  if (!history || !Array.isArray(history.columns) || !Array.isArray(history.data)) return [];
  const dateIndex = history.columns.indexOf('__date_ts');
  const valueIndex = history.columns.indexOf('total_quote');
  if (dateIndex < 0 || valueIndex < 0) return [];
  const points = new Map<number, AccountPoint>();
  for (const row of history.data) {
    const time = finiteValue(row[dateIndex]);
    const value = finiteValue(row[valueIndex]);
    if (time !== undefined && time > 0 && value !== undefined) points.set(time, { time, value });
  }
  return [...points.values()].sort((a, b) => a.time - b.time);
}
export function readObservations(raw: string | null, now = Date.now()): AccountPoint[] {
  try {
    const data: unknown = JSON.parse(raw ?? '[]');
    if (!Array.isArray(data)) return [];
    return data
      .filter(
        (p): p is AccountPoint =>
          p &&
          typeof p === 'object' &&
          finiteValue(p.time) !== undefined &&
          p.time > now - 31 * 86400000 &&
          p.time <= now &&
          finiteValue(p.value) !== undefined,
      )
      .slice(-10000)
      .sort((a, b) => a.time - b.time);
  } catch {
    return [];
  }
}
export function addObservation(points: AccountPoint[], point: AccountPoint): AccountPoint[] {
  if (finiteValue(point.time) === undefined || finiteValue(point.value) === undefined)
    return points;
  const bucket = Math.floor(point.time / 300000);
  return [
    ...points.filter(
      (p) => p.time >= point.time - 31 * 86400000 && Math.floor(p.time / 300000) !== bucket,
    ),
    point,
  ]
    .sort((a, b) => a.time - b.time)
    .slice(-10000);
}
export function observationKey(identity: string): string {
  // An identifier only: never persist the API URL or login credentials with observations.
  let hash = 2166136261;
  for (let i = 0; i < identity.length; i++)
    hash = Math.imul(hash ^ identity.charCodeAt(i), 16777619);
  return `nfi-equity-v1-${hash >>> 0}`;
}
