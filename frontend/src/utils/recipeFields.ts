import type { RecipeSettings } from '@/types/recipe';

export type NumericKey = Exclude<keyof RecipeSettings, 'research_pairs'>;
export const recipeFields: {
  key: NumericKey;
  label: string;
  help: string;
  min: number;
  max: number;
  step: number;
  scale: number;
}[] = [
  {
    key: 'max_open_trades',
    label: 'Position limit',
    help: '6–12 positions. More slots reduce the initial allocation per position.',
    min: 6,
    max: 12,
    step: 1,
    scale: 1,
  },
  {
    key: 'tradable_balance_ratio',
    label: 'Tradable balance (%)',
    help: 'Keep a reserve for fees and adjustments. This is not a maximum drawdown limit.',
    min: 50,
    max: 99,
    step: 1,
    scale: 100,
  },
  {
    key: 'pair_limit',
    label: 'Dynamic pair limit',
    help: '40–80 pairs after volume, age, price, spread and range filters. The actual pool can be smaller.',
    min: 40,
    max: 80,
    step: 1,
    scale: 1,
  },
  {
    key: 'min_age_days',
    label: 'Minimum listing age (days)',
    help: 'Paper trading only. Exclude recently listed assets; default 60 days.',
    min: 60,
    max: 365,
    step: 1,
    scale: 1,
  },
  {
    key: 'min_quote_volume',
    label: 'Minimum 24h volume (USDT)',
    help: 'Paper trading only. A liquidity floor before ranking; default 5 million USDT.',
    min: 0,
    max: 100000000,
    step: 1000000,
    scale: 1,
  },
  {
    key: 'max_spread_ratio',
    label: 'Maximum spread (%)',
    help: 'Paper trading only. Exclude wide bid/ask spreads; default 0.5%.',
    min: 0.1,
    max: 1,
    step: 0.1,
    scale: 100,
  },
  {
    key: 'fee',
    label: 'Fee per side (%)',
    help: 'Charged on entry and exit in both simulations. Default 0.1%; use your actual fee tier.',
    min: 0.01,
    max: 0.5,
    step: 0.01,
    scale: 100,
  },
  {
    key: 'max_slippage',
    label: 'Entry slippage tolerance (%)',
    help: 'NFI entry guard; default 2%. This does not add slippage costs to historical backtests.',
    min: 0.1,
    max: 2,
    step: 0.1,
    scale: 100,
  },
];
