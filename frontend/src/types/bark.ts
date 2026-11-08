export interface BarkRules {
  enabled: boolean;
  profit_enabled: boolean;
  profit_threshold_pct: number;
  loss_enabled: boolean;
  loss_threshold_pct: number;
  state_enabled: boolean;
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
  history: {
    at: string;
    event: 'profit' | 'loss' | 'state' | 'test';
    success: boolean;
    error: string | null;
  }[];
}
