import type { StrategyBacktestResult, WalletHistory } from '@/types';

export interface DrawdownPoint {
  timestamp: number;
  balance: number;
  ratio: number;
}
export interface DrawdownEpisode {
  peak: number;
  peakBalance: number;
  trough: number;
  troughBalance: number;
  recovered: number | null;
  ratio: number;
  amount: number;
}
export interface BacktestDrawdown {
  source: 'wallet' | 'wallet_summary' | 'closed_trades' | 'unavailable';
  points: DrawdownPoint[];
  maxRatio: number | null;
  maxAmount: number | null;
  maximum: DrawdownEpisode | null;
  longest: DrawdownEpisode | null;
  longestMs: number | null;
  end: number | null;
}
const toMs = (value: number) => (value < 1e12 ? value * 1000 : value);
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

function walletPoints(wallet: WalletHistory): { timestamp: number; balance: number }[] | null {
  if (!Array.isArray(wallet.columns) || !Array.isArray(wallet.data) || !wallet.data.length)
    return null;
  const time = wallet.columns.indexOf('__date_ts');
  const value = wallet.columns.indexOf('total_quote');
  if (time < 0 || value < 0 || wallet.length !== wallet.data.length) return null;
  const points = new Map<number, number>();
  for (const row of wallet.data) {
    const timestamp = row[time];
    const balance = row[value];
    if (!finite(timestamp) || !finite(balance)) return null;
    points.set(toMs(timestamp), balance);
  }
  return [...points]
    .map(([timestamp, balance]) => ({ timestamp, balance }))
    .sort((a, b) => a.timestamp - b.timestamp);
}

function closedPoints(result: StrategyBacktestResult) {
  if (!Array.isArray(result.trades) || result.trades.length !== result.total_trades) return null;
  const profits = new Map<number, number>();
  for (const trade of result.trades) {
    if (!finite(trade.close_timestamp) || !finite(trade.profit_abs) || trade.is_open) return null;
    const timestamp = toMs(trade.close_timestamp);
    profits.set(timestamp, (profits.get(timestamp) ?? 0) + trade.profit_abs);
  }
  let balance = result.starting_balance;
  // Combine simultaneous closes before comparing with a high-water mark.
  return [...profits]
    .sort(([a], [b]) => a - b)
    .map(([timestamp, profit]) => {
      balance += profit;
      return { timestamp, balance };
    });
}

export function backtestDrawdown(
  result: StrategyBacktestResult,
  wallet?: WalletHistory,
): BacktestDrawdown {
  const empty: BacktestDrawdown = {
    source: 'unavailable',
    points: [],
    maxRatio: null,
    maxAmount: null,
    maximum: null,
    longest: null,
    longestMs: null,
    end: null,
  };
  const start = toMs(result.backtest_start_ts);
  const end = toMs(result.backtest_end_ts);
  if (
    !finite(start) ||
    !finite(end) ||
    end <= start ||
    !finite(result.starting_balance) ||
    result.starting_balance <= 0
  )
    return empty;
  const walletCurve = wallet ? walletPoints(wallet) : null;
  const summary = result.wallet_stats;
  if (
    !walletCurve &&
    summary &&
    finite(summary.max_drawdown_abs) &&
    finite(summary.max_drawdown_account)
  ) {
    return {
      ...empty,
      source: 'wallet_summary',
      maxRatio: finite(summary.max_relative_drawdown)
        ? summary.max_relative_drawdown
        : summary.max_drawdown_account,
      maxAmount: summary.max_drawdown_abs,
      end,
    };
  }
  const curve = walletCurve ?? closedPoints(result);
  if (!curve || curve.some((point) => point.timestamp < start || point.timestamp > end))
    return empty;
  const points = [...curve];
  if (points[0]?.timestamp !== start)
    points.unshift({ timestamp: start, balance: result.starting_balance });
  if (points.at(-1)!.timestamp < end)
    points.push({ timestamp: end, balance: points.at(-1)!.balance });
  const episodes: DrawdownEpisode[] = [];
  const underwater: DrawdownPoint[] = [];
  let high = result.starting_balance;
  let highDate = start;
  let active: DrawdownEpisode | null = null;
  let maxRatio = 0;
  let maxAmount = 0;
  for (const point of points) {
    const tolerance = Math.max(1, Math.abs(high), Math.abs(point.balance)) * 1e-10;
    if (point.balance >= high - tolerance) {
      if (active) {
        active.recovered = point.timestamp;
        episodes.push(active);
        active = null;
      }
      high = Math.max(high, point.balance);
      highDate = point.timestamp;
    } else {
      if (!active)
        active = {
          peak: highDate,
          peakBalance: high,
          trough: point.timestamp,
          troughBalance: point.balance,
          recovered: null,
          ratio: 0,
          amount: 0,
        };
      if (point.balance < active.troughBalance - tolerance) {
        active.trough = point.timestamp;
        active.troughBalance = point.balance;
      }
      active.amount = high - active.troughBalance;
      active.ratio = active.amount / high;
    }
    const amount = Math.max(0, high - point.balance);
    const ratio = amount > tolerance ? amount / high : 0;
    maxRatio = Math.max(maxRatio, ratio);
    maxAmount = Math.max(maxAmount, amount > tolerance ? amount : 0);
    underwater.push({ ...point, ratio });
  }
  if (active) episodes.push(active);
  const duration = (episode: DrawdownEpisode) => (episode.recovered ?? end) - episode.peak;
  const maximum = episodes.reduce<DrawdownEpisode | null>(
    (best, episode) => (!best || episode.ratio > best.ratio ? episode : best),
    null,
  );
  const longest = episodes.reduce<DrawdownEpisode | null>(
    (best, episode) => (!best || duration(episode) > duration(best) ? episode : best),
    null,
  );
  return {
    source: walletCurve ? 'wallet' : 'closed_trades',
    points: underwater,
    maxRatio,
    maxAmount,
    maximum,
    longest,
    longestMs: longest ? duration(longest) : 0,
    end,
  };
}
