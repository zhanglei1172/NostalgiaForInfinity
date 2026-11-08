export interface LiveBalance {
  uid: string;
  free: number;
  used: number;
  total: number;
  checked_at: string;
}
export interface LiveSettings {
  configured: boolean;
  exchange: string;
  revision: number;
  runtime_revision: number;
  phase: 'setup' | 'loading' | 'applying' | 'ready' | 'error';
  error: string | null;
  account_label: string;
  account_uid: string | null;
  available_capital: number | null;
  credentials_configured: boolean;
  updated_at: string | null;
  recipe_revision: number | null;
  state: string;
  database: { trades: number; open_trades: number; open_orders: number };
}
