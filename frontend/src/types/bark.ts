export interface BarkRules {
  enabled: boolean;
  profit_enabled: boolean;
  profit_threshold_pct: number;
  loss_enabled: boolean;
  loss_threshold_pct: number;
  state_enabled: boolean;
  trade_error_enabled: boolean;
  exchange_error_enabled: boolean;
  recovery_enabled: boolean;
  exchange_grace_minutes: number;
  cooldown_minutes: number;
}
export interface BarkSettings extends BarkRules {
  revision: number;
  updated_at: string | null;
  role: 'paper' | 'live';
  destination_configured: boolean;
  check_interval_seconds: number;
  last_checked_at: string | null;
  roi_pct: number | null;
  bot_state: string | null;
  monitor_error: string | null;
  operational_events_supported?: boolean;
  active_incidents?: {
    code: string;
    operation: string;
    pair: string | null;
    since: number;
    at: number;
  }[];
  history: {
    at: string;
    event: 'profit' | 'loss' | 'state' | 'test' | 'trade_error' | 'exchange_error' | 'recovery';
    success: boolean;
    error: string | null;
    context?: { code: string; operation: string; pair: string | null; count: number } | null;
  }[];
}
