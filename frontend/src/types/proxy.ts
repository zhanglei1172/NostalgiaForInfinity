export interface ProxyDraft {
  enabled: boolean;
  protocol: 'socks5h' | 'socks5' | 'http' | 'https';
  host: string;
  port: number;
  auth_enabled: boolean;
}

export interface ProxySettings {
  role: 'paper' | 'live';
  revision: number;
  settings: ProxyDraft & { username_configured: boolean; password_configured: boolean };
  active_revision: number;
  active_enabled: boolean;
  runtime_revision: number | null;
  runtime_enabled: boolean | null;
  pending_changes: boolean;
  updated_at: string | null;
  applied_at: string | null;
  can_apply: boolean;
  apply_block_reason: string | null;
}

export interface ProxyCheck {
  success: boolean;
  checked_at: string;
  checks: Record<
    'rest_sync' | 'rest_async' | 'websocket',
    { success: boolean; latency_ms?: number; error?: string }
  >;
}
