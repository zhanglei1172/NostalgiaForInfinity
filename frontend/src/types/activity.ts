export interface StrategyActivity {
  as_of: string;
  exchange: string;
  dry_run: boolean;
  state: string;
  strategy: string;
  timeframe: string;
  open_trades: number;
  free_slots: number;
  pair_count: number;
  reasons: string[];
  journal_since: string;
  pairs: {
    pair: string;
    candle_at: string | null;
    analyzed_at: string | null;
    signal: 'unavailable' | 'entry' | 'none' | 'conflict';
    entry_tag: string | null;
    exit_tag: string | null;
    reasons: string[];
    lock_until: string | null;
  }[];
  fills: {
    trade_id: number;
    pair: string;
    side: string;
    at: string;
    filled: number;
    price: number | null;
    order_open: boolean;
    tag: string | null;
    exit_reason: string | null;
  }[];
  rejections: { at: string; pair: string; reason: string }[];
}
