"""Build a live snapshot from the applied paper recipe."""

import math

from nfi_research.recipe import RecipeSettings, recipe_config


def build_config(base, blacklist, document, capital):
  if not math.isfinite(capital) or capital < 100:
    raise ValueError("初始预算必须是至少 100 USDT 的有限数字；还需满足实际最小下单金额。")
  if document.get("schema_version") != 1:
    raise ValueError("配方版本不兼容。")
  settings = RecipeSettings(**document["settings"]).model_dump()
  base["exchange"].update(name="okx", key="", secret="", password="", pair_blacklist=blacklist)
  config = recipe_config(base, {**document, "settings": settings})
  config.update(
    dry_run=False,
    trading_mode="spot",
    margin_mode="",
    strategy="NostalgiaForInfinityX8",
    bot_name="NFI_Live_okx_spot",
    available_capital=capital,
    initial_state="stopped",
    force_entry_enable=False,
    cancel_open_orders_on_exit=False,
    telegram={"enabled": False, "token": "", "chat_id": ""},
    api_server={
      "enabled": True,
      "listen_ip_address": "0.0.0.0",
      "listen_port": 8080,
      "verbosity": "error",
      "enable_openapi": False,
      "CORS_origins": [],
    },
  )
  # Real balances and fee tiers come from the exchange. available_capital includes subsequent P&L.
  for key in ("original_config", "dry_run_wallet", "tradable_balance_ratio", "fee", "add_config_files"):
    config.pop(key, None)
  return config
