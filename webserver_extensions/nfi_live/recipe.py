"""Independent live recipe drafts and explicitly confirmed, stopped-worker updates."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from freqtrade.enums import State
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_rpc_optional
from nfi_account import SecretRoute, account_manager
from nfi_account.credentials import AccountManager
from nfi_research.recipe import RecipeSettings, exchange_defaults, recipe_config, validate_research_pairs
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .storage import LiveError, atomic_json, read_json

LIVE_FIELDS = ("max_open_trades", "pair_limit", "min_age_days", "min_quote_volume", "max_spread_ratio", "max_slippage")


class SaveDraft(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  revision: int = Field(ge=0)
  settings: RecipeSettings


class ApplyDraft(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  revision: int = Field(ge=0)
  live_revision: int = Field(ge=0)
  current_password: SecretStr
  confirm_live: Literal[True]


def document(value):
  if not isinstance(value, dict) or value.get("schema_version") != 1:
    raise LiveError("live_recipe_invalid", 503)
  revision = value.get("revision")
  if type(revision) is not int or revision < 0:
    raise LiveError("live_recipe_invalid", 503)
  try:
    settings = RecipeSettings(**value["settings"]).model_dump()
  except (KeyError, TypeError, ValueError):
    raise LiveError("live_recipe_invalid", 503) from None
  return {"schema_version": 1, "revision": revision, "settings": settings, "updated_at": value.get("updated_at")}


def paper_document(store, name="active"):
  return document(
    read_json(store.source / f"recipes/{name}.json")
    or {"schema_version": 1, "revision": 0, "settings": exchange_defaults({"exchange": {"name": "okx"}})}
  )


def current_document(profile):
  return document(
    {
      "schema_version": 1,
      "revision": profile.get("nfi_live_recipe_revision", 0),
      "settings": profile.get("nfi_recipe_settings"),
      "updated_at": profile.get("nfi_live_recipe_updated_at"),
    }
  )


def draft_document(store):
  value = read_json(store.directory / ".nfi-live-recipe.json")
  if value is not None:
    return document(value)
  profile = store.profile()
  initial = current_document(profile) if profile and profile.get("nfi_recipe_settings") else paper_document(store)
  return {**initial, "revision": 0, "updated_at": None}


def initial_document(store):
  """A pre-account Web draft takes precedence over the paper snapshot at first setup."""
  value = read_json(store.directory / ".nfi-live-recipe.json")
  return (document(value), True) if value is not None else (paper_document(store), False)


def apply_blocker(store, config, profile, recovery=False):
  if not profile:
    return "live_recipe_account_required"
  rpc = get_rpc_optional()
  status = store.status()
  if recovery and not rpc and status["phase"] == "error":
    counts = store.database_counts()
    return "live_recipe_has_positions" if counts["open_trades"] or counts["open_orders"] else None
  if (
    not rpc
    or not hasattr(rpc._freqtrade, "_measure_execution")
    or status["phase"] != "ready"
    or status["revision"] != profile["nfi_live_revision"]
    or config.get("nfi_live_revision") != profile["nfi_live_revision"]
  ):
    return "live_apply_pending"
  if rpc._freqtrade.state != State.STOPPED:
    return "live_stop_required"
  counts = store.database_counts()
  if counts["open_trades"] or counts["open_orders"]:
    return "live_recipe_has_positions"
  return None


def strategy_info(store, profile):
  def digest(path):
    if not path.is_file() or path.is_symlink():
      return None
    return hashlib.sha256(path.read_bytes()).hexdigest()

  live = digest(store.directory / "strategies/NostalgiaForInfinityX8.py") if profile else None
  research = digest(store.source / "NostalgiaForInfinityX8.py")
  return {
    "name": "NostalgiaForInfinityX8",
    "live_sha256": live,
    "research_sha256": research,
    "matches": live == research if live else None,
  }


def recipe_info(store, config):
  profile = store.profile()
  paper = paper_document(store)
  saved = draft_document(store)
  active = current_document(profile) if profile and profile.get("nfi_recipe_settings") else None
  previous = read_json(store.directory / ".nfi-live-recipe-previous.json")
  previous = document(previous) if previous else None
  blocker = apply_blocker(store, config, profile)
  status = store.status()
  rpc = get_rpc_optional()
  runtime = None
  if rpc and hasattr(rpc._freqtrade, "_measure_execution") and config.get("nfi_recipe_settings"):
    runtime = {**config["nfi_recipe_settings"], "max_open_trades": config["max_open_trades"]}
    runtime["max_slippage"] = config.get("nfi_parameters", {}).get("max_slippage", runtime["max_slippage"])
  return {
    "exchange": "okx",
    "saved": saved,
    "defaults": exchange_defaults({"exchange": {"name": "okx"}}),
    "applied_settings": active["settings"] if active else None,
    "runtime_settings": runtime,
    "applied_revision": (profile or {}).get("nfi_live_recipe_revision"),
    "runtime_revision": config.get("nfi_live_recipe_revision"),
    "live_revision": (profile or {}).get("nfi_live_revision", 0),
    "runtime_live_revision": config.get("nfi_live_revision", 0),
    "phase": status["phase"],
    "error": status.get("error"),
    "configured": profile is not None,
    "can_apply": blocker is None,
    "apply_blocker": blocker,
    "can_rollback": previous is not None and apply_blocker(store, config, profile, recovery=True) is None,
    "previous": previous,
    "paper_applied": paper,
    "paper_saved": paper_document(store, "saved"),
    "live_fields": LIVE_FIELDS,
    "strategy": strategy_info(store, profile),
  }


def update_profile(profile, value):
  if (
    profile.get("dry_run") is not False
    or profile.get("exchange", {}).get("name") != "okx"
    or profile.get("trading_mode") != "spot"
    or profile.get("strategy") != "NostalgiaForInfinityX8"
  ):
    raise LiveError("live_recipe_unsupported", 409)
  updated = recipe_config(profile, value)
  # Real balances and fee tiers always come from OKX, regardless of simulation metadata.
  for key in ("original_config", "dry_run_wallet", "tradable_balance_ratio", "fee", "add_config_files"):
    updated.pop(key, None)
  updated.update(
    initial_state="stopped",
    nfi_live_revision=profile["nfi_live_revision"] + 1,
    nfi_live_recipe_revision=value["revision"],
    nfi_live_recipe_updated_at=datetime.now(UTC).isoformat(),
  )
  return updated


def apply_recipe(store, config, manager, payload, rollback=False):
  from . import verify_password

  with store.exclusive():
    verify_password(manager, payload.current_password)
    profile = store.profile()
    saved = draft_document(store)
    if saved["revision"] != payload.revision or (profile or {}).get("nfi_live_revision", 0) != payload.live_revision:
      raise LiveError("live_recipe_revision_conflict", 409)
    blocker = apply_blocker(store, config, profile, recovery=rollback)
    if blocker:
      raise LiveError(blocker, 409)
    value = saved
    if rollback:
      previous = read_json(store.directory / ".nfi-live-recipe-previous.json")
      if not previous:
        raise LiveError("live_recipe_no_previous", 409)
      value = {**document(previous), "revision": saved["revision"] + 1, "updated_at": datetime.now(UTC).isoformat()}
    validate_research_pairs(profile, value["settings"])
    updated = update_profile(profile, value)
    previous = current_document(profile) if profile.get("nfi_recipe_settings") else None
    if previous:
      atomic_json(store.directory / ".nfi-live-recipe-previous.json", previous)
    if rollback:
      atomic_json(store.directory / ".nfi-live-recipe.json", value)
    store.write_status("applying", updated["nfi_live_revision"])
    atomic_json(store.profile_path, updated)
    return {
      "status": "reloading",
      "requested_revision": value["revision"],
      "live_revision": updated["nfi_live_revision"],
      "state": "stopped",
    }


def configure_live_recipe_api(app, config, store):
  from . import same_origin

  router = APIRouter(
    prefix="/api/v1/live-recipe", route_class=SecretRoute, dependencies=[Depends(api_auth.http_basic_or_jwt_token)]
  )

  @router.get("")
  def info():
    with store.exclusive():
      return recipe_info(store, config)

  @router.put("")
  def save(payload: SaveDraft, request: Request):
    same_origin(request)
    with store.exclusive():
      current = draft_document(store)
      if payload.revision != current["revision"]:
        raise LiveError("live_recipe_revision_conflict", 409)
      profile = store.profile() or {"exchange": {"pair_blacklist": []}}
      validate_research_pairs(profile, payload.settings.model_dump())
      atomic_json(
        store.directory / ".nfi-live-recipe.json",
        {
          "schema_version": 1,
          "revision": current["revision"] + 1,
          "settings": payload.settings.model_dump(),
          "updated_at": datetime.now(UTC).isoformat(),
        },
      )
      return recipe_info(store, config)

  @router.post("/apply")
  def apply(payload: ApplyDraft, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    same_origin(request)
    return apply_recipe(store, config, manager, payload)

  @router.post("/rollback")
  def rollback(payload: ApplyDraft, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    same_origin(request)
    return apply_recipe(store, config, manager, payload, rollback=True)

  app.include_router(router)
