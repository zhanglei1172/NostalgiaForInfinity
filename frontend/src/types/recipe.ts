export interface RecipeSettings {
  max_open_trades: number;
  tradable_balance_ratio: number;
  pair_limit: number;
  min_age_days: number;
  min_quote_volume: number;
  max_spread_ratio: number;
  fee: number;
  max_slippage: number;
  research_pairs: string[];
}
export interface RecipeInfo {
  exchange: string;
  saved: { revision: number; settings: RecipeSettings; updated_at?: string };
  defaults: RecipeSettings;
  applied_revision: number | null;
  applied_settings: RecipeSettings | null;
  can_apply: boolean;
}

export interface LiveRecipeInfo extends RecipeInfo {
  runtime_settings: RecipeSettings | null;
  configured: boolean;
  live_revision: number;
  runtime_live_revision: number;
  runtime_revision: number | null;
  phase: string;
  error: string | null;
  apply_blocker: string | null;
  can_rollback: boolean;
  previous: RecipeInfo['saved'] | null;
  paper_applied: RecipeInfo['saved'];
  paper_saved: RecipeInfo['saved'];
  live_fields: (keyof RecipeSettings)[];
  strategy: {
    name: string;
    live_sha256: string | null;
    research_sha256: string | null;
    matches: boolean | null;
  };
}
