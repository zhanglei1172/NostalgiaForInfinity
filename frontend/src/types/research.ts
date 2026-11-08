export interface PreparationStatus {
  running: boolean;
  status: 'idle' | 'running' | 'success' | 'failed';
  timeframe: string | null;
  completed: number;
  total: number;
  error: string | null;
  start_date?: string;
  end_date?: string;
}
export interface ResearchInfo {
  recipe_revision?: number;
  exchange: string;
  trading_mode: string;
  pairs: string[];
  timeframes: string[];
  stake_currency: string;
  starting_balance: number;
  max_open_trades: number;
  fee: number;
  preparation: PreparationStatus;
}
