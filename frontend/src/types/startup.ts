export interface StartupSettings {
  auto_start: boolean;
  revision: number;
  updated_at: string | null;
  role: 'paper' | 'live';
  can_enable: boolean;
}
