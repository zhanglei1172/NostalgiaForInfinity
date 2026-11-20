"""Trading-mode settings shared by isolated live and research instances."""

import math
import os
from copy import deepcopy

from .storage import LiveError

LEVERAGE_KEYS = (
  "futures_mode_leverage",
  "futures_mode_leverage_rebuy_mode",
  "futures_mode_leverage_grind_mode",
  "futures_mode_leverage_long",
  "futures_mode_leverage_long_rebuy_mode",
  "futures_mode_leverage_long_grind_mode",
  "futures_mode_leverage_short",
  "futures_mode_leverage_short_rebuy_mode",
  "futures_mode_leverage_short_grind_mode",
)


def instance_mode():
  value = os.environ.get("NFI_TRADING_MODE", "spot")
  if value not in ("spot", "futures"):
    raise LiveError("live_trading_mode_invalid")
  return value


def trading_settings(config=None):
  config = config or {}
  mode = config.get("trading_mode", instance_mode())
  leverage = config.get("nfi_live_leverage", config.get("nfi_parameters", {}).get("futures_mode_leverage", 1.0))
  return {"trading_mode": mode, "margin_mode": "isolated" if mode == "futures" else "", "leverage": leverage}


def apply_trading_settings(config, mode, leverage=1.0):
  if mode not in ("spot", "futures") or not math.isfinite(leverage) or not 1 <= leverage <= 5:
    raise LiveError("live_trading_mode_invalid")
  config.update(trading_mode=mode, margin_mode="isolated" if mode == "futures" else "")
  market_type = "swap" if mode == "futures" else "spot"
  for key in ("ccxt_config", "ccxt_async_config"):
    transport = config.setdefault("exchange", {}).setdefault(key, {})
    transport.setdefault("options", {}).update(defaultType=market_type, fetchMarkets={"types": [market_type]})
    if mode == "futures" and config["exchange"].get("name") == "okx":
      # Candle-based volume scans exceed OKX limits with the legacy 60 ms setting.
      transport.update(enableRateLimit=True, rateLimit=max(200, transport.get("rateLimit", 200)))
  if mode == "futures":
    config["nfi_live_leverage"] = leverage
    config.setdefault("nfi_parameters", {}).update({key: leverage for key in LEVERAGE_KEYS})
    # Old top-level overrides otherwise take precedence over nfi_parameters in NFI.
    for key in LEVERAGE_KEYS:
      config.pop(key, None)
  else:
    config.pop("nfi_live_leverage", None)
    for key in LEVERAGE_KEYS:
      config.get("nfi_parameters", {}).pop(key, None)
      config.pop(key, None)
  return config


def public_research_snapshot(profile, document, mode=None):
  """An allowlist, never a copy of a live profile or its transport/authentication."""
  profile = profile or {}
  selected = trading_settings(profile or {"trading_mode": mode or instance_mode()})
  config = {
    **selected,
    "dry_run_wallet": profile.get("available_capital", 10000),
    "tradable_balance_ratio": 1.0,
    "nfi_parameters": {
      key: deepcopy(value)
      for key, value in profile.get("nfi_parameters", {}).items()
      if key in (*LEVERAGE_KEYS, "max_slippage", "num_cores_indicators_calc", "derisk_enable", "stops_enable")
    },
  }
  if selected["trading_mode"] == "futures":
    config["nfi_live_leverage"] = selected["leverage"]
    config["nfi_parameters"].update({key: selected["leverage"] for key in LEVERAGE_KEYS})
  config.pop("leverage")
  return {"schema_version": 1, "config": config, "recipe": deepcopy(document)}


def publish_research_snapshot(store, profile=None):
  from .recipe import current_document, initial_document
  from .storage import atomic_json

  profile = profile or store.profile()
  # Seed the same immutable strategy copy for both services before account setup.
  import shutil

  target = store.directory / "strategies/NostalgiaForInfinityX8.py"
  if not target.exists():
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(store.source / target.name, target)
  recipe = current_document(profile) if profile and profile.get("nfi_recipe_settings") else initial_document(store)[0]
  atomic_json(store.directory / "research-public/snapshot.json", public_research_snapshot(profile, recipe))
