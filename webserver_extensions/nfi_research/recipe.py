"""Bounded paper/research recipes. Never persist credentials or change account balances."""

import json
import os
import re
import tempfile
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_rpc
from freqtrade.rpc.rpc import RPC
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULTS = json.loads(Path(__file__).with_name("recipe_defaults.json").read_text())
LOCK = threading.RLock()


def exchange_defaults(config):
  defaults = deepcopy(DEFAULTS)
  if config.get("exchange", {}).get("name") == "okx":
    replacements = {"VET/USDT": "POL/USDT", "RUNE/USDT": "DYDX/USDT", "QNT/USDT": "COMP/USDT", "CAKE/USDT": "ZEC/USDT"}
    defaults["research_pairs"] = [replacements.get(pair, pair) for pair in defaults["research_pairs"]]
  return defaults


class RecipeSettings(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
  max_open_trades: int = Field(ge=6, le=12)
  tradable_balance_ratio: float = Field(ge=0.5, le=0.99)
  pair_limit: int = Field(ge=40, le=80)
  min_age_days: int = Field(ge=60, le=365)
  min_quote_volume: float = Field(ge=0, le=100000000)
  max_spread_ratio: float = Field(ge=0.001, le=0.01)
  fee: float = Field(ge=0.0001, le=0.005)
  max_slippage: float = Field(ge=0.001, le=0.02)
  research_pairs: list[str] = Field(min_length=3, max_length=80)

  @field_validator("research_pairs")
  @classmethod
  def valid_pairs(cls, pairs):
    if len(set(pairs)) != len(pairs) or any(not re.fullmatch(r"[A-Z0-9]{2,20}/USDT", p) for p in pairs):
      raise ValueError("Use unique spot BASE/USDT symbols, without regex or leveraged tokens")
    if any(re.search(r"(?:UP|DOWN|BULL|BEAR|[1235][SL])/", p) for p in pairs):
      raise ValueError("Leveraged tokens are excluded")
    return pairs


class SaveRecipe(BaseModel):
  model_config = ConfigDict(extra="forbid")
  revision: int = Field(ge=0)
  settings: RecipeSettings


class ApplyRecipe(BaseModel):
  model_config = ConfigDict(extra="forbid")
  revision: int = Field(ge=0)


def supported(config):
  return (
    config.get("dry_run") is True
    and config.get("trading_mode", "spot") == "spot"
    and config.get("exchange", {}).get("name") in ("binance", "okx")
    and config.get("strategy") == "NostalgiaForInfinityX8"
  )


class RecipeStore:
  def __init__(self, config):
    self.defaults = exchange_defaults(config)
    self.directory = Path(os.environ.get("NFI_RECIPE_DIR", str(Path(config["user_data_dir"]) / "recipes")))

  def read(self, name="saved"):
    path = self.directory / f"{name}.json"
    if not path.exists():
      return {"schema_version": 1, "revision": 0, "settings": RecipeSettings(**self.defaults).model_dump()}
    value = json.loads(path.read_text())
    if value["schema_version"] != 1 or not isinstance(value["revision"], int):
      raise ValueError("Unsupported recipe version")
    value["settings"] = RecipeSettings(**value["settings"]).model_dump()
    return value

  def write(self, name, value):
    self.directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".recipe-", dir=self.directory)
    try:
      with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.directory / f"{name}.json")
    finally:
      if os.path.exists(temporary):
        os.unlink(temporary)

  def save(self, payload):
    with LOCK:
      current = self.read()
      if payload.revision != current["revision"]:
        raise HTTPException(409, detail="recipe_revision_conflict")
      self.write("previous-saved", current)
      value = {
        "schema_version": 1,
        "revision": current["revision"] + 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "settings": payload.settings.model_dump(),
      }
      self.write("saved", value)
      return value


def recipe_config(config, document, research=False):
  result = deepcopy(config)
  settings = document["settings"]
  result.update(
    max_open_trades=settings["max_open_trades"],
    tradable_balance_ratio=settings["tradable_balance_ratio"],
    stake_amount="unlimited",
    fee=settings["fee"],
    timeframe="5m",
    use_exit_signal=True,
    exit_profit_only=False,
    ignore_roi_if_entry_signal=True,
    nfi_recipe_revision=document["revision"],
    nfi_recipe_settings=deepcopy(settings),
  )
  result.setdefault("nfi_parameters", {}).update(
    max_slippage=settings["max_slippage"], num_cores_indicators_calc=1, derisk_enable=True, stops_enable=True
  )
  for key in ("max_slippage", "num_cores_indicators_calc", "derisk_enable", "stops_enable"):
    result.pop(key, None)  # Legacy top-level NFI overrides must not shadow the recipe.
  if research:
    validate_research_pairs(config, settings)
    result["exchange"]["pair_whitelist"] = settings["research_pairs"].copy()
    result["pairlists"] = [{"method": "StaticPairList"}]
  else:
    result["exchange"]["pair_whitelist"] = []
    result["pairlists"] = [
      {
        "method": "VolumePairList",
        "number_assets": 130,
        "sort_key": "quoteVolume",
        "min_value": settings["min_quote_volume"],
        "refresh_period": 1800,
      },
      {"method": "FullTradesFilter"},
      {"method": "AgeFilter", "min_days_listed": settings["min_age_days"]},
      {"method": "PriceFilter", "low_price_ratio": 0.003},
      {"method": "SpreadFilter", "max_spread_ratio": settings["max_spread_ratio"]},
      {
        "method": "RangeStabilityFilter",
        "lookback_days": 3,
        "min_rate_of_change": 0.03,
        "max_rate_of_change": 0.95,
        "refresh_period": 1800,
      },
      {"method": "VolumePairList", "number_assets": settings["pair_limit"], "sort_key": "quoteVolume"},
    ]
  # Freqtrade exports original_config, rather than the runtime dictionary, in result archives.
  original = result.setdefault("original_config", {})
  for key in (
    "max_open_trades",
    "tradable_balance_ratio",
    "stake_amount",
    "fee",
    "timeframe",
    "use_exit_signal",
    "exit_profit_only",
    "ignore_roi_if_entry_signal",
    "nfi_parameters",
    "nfi_recipe_revision",
    "nfi_recipe_settings",
    "pairlists",
  ):
    original[key] = deepcopy(result[key])
  original.setdefault("exchange", {})["pair_whitelist"] = result["exchange"]["pair_whitelist"].copy()
  return result


def validate_research_pairs(config, settings):
  blacklist = config.get("exchange", {}).get("pair_blacklist", [])
  if any(re.fullmatch(pattern, pair) for pattern in blacklist for pair in settings["research_pairs"]):
    raise HTTPException(422, detail="recipe_blacklisted_pair")


def apply_paper_recipe(config):
  """Called after environment/CLI config parsing, before strategy and exchange initialization."""
  if os.environ.get("NFI_RECIPE_ROLE") != "paper" or str(config.get("runmode")) != "dry_run":
    return
  if not supported(config):
    raise ValueError("Paper recipe requires Binance or OKX spot dry-run with NostalgiaForInfinityX8")
  document = RecipeStore(config).read("active")
  config.update(recipe_config(config, document))


def configure_recipe_api(app, config):
  if os.environ.get("NFI_RECIPE_ROLE") != "paper":
    return
  store = RecipeStore(config)
  router = APIRouter(prefix="/api/v1/recipe", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

  def info():
    return {
      "saved": store.read(),
      "exchange": config["exchange"]["name"],
      "defaults": RecipeSettings(**store.defaults).model_dump(),
      "applied_revision": config.get("nfi_recipe_revision"),
      "applied_settings": config.get("nfi_recipe_settings"),
      "can_apply": supported(config),
    }

  @router.get("")
  def get_recipe():
    return info()

  @router.put("")
  def save_recipe(payload: SaveRecipe):
    validate_research_pairs(config, payload.settings.model_dump())
    store.save(payload)
    return info()

  @router.post("/apply")
  def apply_recipe(payload: ApplyRecipe, rpc: Annotated[RPC, Depends(get_rpc)]):
    if not supported(config):
      raise HTTPException(409, detail="recipe_paper_only")
    with LOCK:
      document = store.read()
      if payload.revision != document["revision"]:
        raise HTTPException(409, detail="recipe_revision_conflict")
      store.write("previous-active", store.read("active"))
      store.write("active", document)
      rpc._rpc_reload_config()
    return {"status": "reloading", "requested_revision": document["revision"]}

  app.include_router(router)
