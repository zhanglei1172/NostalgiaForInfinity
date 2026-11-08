"""Web-managed live accounts. Importing this module never starts a trading process."""

import math
import os
import re
import secrets
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated

import ccxt
import rapidjson
from fastapi import APIRouter, Depends, Request
from freqtrade.enums import State
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_rpc, get_rpc_optional
from freqtrade.rpc.rpc import RPC
from nfi_account import SecretRoute, account_manager
from nfi_account.credentials import AccountError, AccountManager, password_hash
from nfi_account.origin import is_same_origin
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .config import build_config
from .storage import CONTROL_LOCK, LiveError, LiveStore, atomic_json


class Credentials(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
  api_key: SecretStr | None = None
  api_secret: SecretStr | None = None
  passphrase: SecretStr | None = None


class SaveSettings(Credentials):
  revision: int = Field(ge=0)
  account_label: str = Field(min_length=1, max_length=60)
  available_capital: float = Field(ge=100, le=1_000_000_000)
  current_password: SecretStr

  @field_validator("account_label")
  @classmethod
  def label(cls, value):
    if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
      raise ValueError("Invalid account label")
    return value.strip()


class SetupAccount(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  username: str
  password: SecretStr


class ReloadSettings(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  current_password: SecretStr


def same_origin(request, local=False):
  host = request.url.hostname
  if local and host not in ("127.0.0.1", "localhost", "::1"):
    raise LiveError("live_setup_local_only", 403)
  if not is_same_origin(request, allow_proxy=not local):
    raise LiveError("live_origin_rejected", 403)


def resolve_credentials(payload, existing=None):
  result = {}
  for field, key in (("api_key", "key"), ("api_secret", "secret"), ("passphrase", "password")):
    value = getattr(payload, field)
    value = value.get_secret_value().strip() if value else ""
    result[key] = value or (existing or {}).get(key, "")
    if not result[key] or len(result[key]) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in result[key]):
      raise LiveError("live_credentials_required")
  return result


def check_connection(credentials, transport):
  """Read OKX trading-account identity and USDT balance. Never submit an order."""
  try:
    client = ccxt.okx(
      {
        **transport,
        "apiKey": credentials["key"],
        "secret": credentials["secret"],
        "password": credentials["password"],
        "enableRateLimit": True,
        "timeout": 12000,
        "verbose": False,
        "options": {"defaultType": "spot", "fetchMarkets": {"types": ["spot"]}},
      }
    )
    identity = client.private_get_account_config()
    uid = str(identity["data"][0]["uid"])
    if not re.fullmatch(r"[0-9]{1,40}", uid):
      raise ValueError("Invalid identity")
    balance = client.fetch_balance()
    usdt = balance.get("USDT", {})
    result = {
      "uid": uid,
      "free": float(usdt.get("free") or 0),
      "used": float(usdt.get("used") or 0),
      "total": float(usdt.get("total") or 0),
      "checked_at": datetime.now(UTC).isoformat(),
    }
    if not all(math.isfinite(result[key]) and result[key] >= 0 for key in ("free", "used", "total")):
      raise ValueError("Invalid balance")
    return result
  except (ccxt.BaseError, KeyError, IndexError, TypeError, ValueError):
    raise LiveError("live_connection_failed") from None


def verify_password(manager, password):
  with manager.lock:
    manager._verify_current(password.get_secret_value())


def require_stopped():
  rpc = get_rpc_optional()
  if rpc and rpc._freqtrade.state != State.STOPPED:
    raise LiveError("live_stop_required", 409)


def initialize_account(store, manager, payload):
  password = payload.password.get_secret_value()
  with store.exclusive(), manager.lock:
    if manager.state or manager.path.exists():
      raise LiveError("live_setup_complete", 409)
    valid_username = bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", payload.username))
    valid_password = 12 <= len(password) <= 128 and not any(ord(c) < 32 or ord(c) == 127 for c in password)
    if not manager.attempts.verify("setup", lambda: valid_username and valid_password):
      if not valid_username:
        raise LiveError("live_username_invalid")
      raise AccountError("account_invalid_password")
    salt = secrets.token_hex(16)
    now = datetime.now(UTC).isoformat()
    manager._persist(
      {
        "version": 1,
        "username": payload.username,
        "salt": salt,
        "password_hash": password_hash(password, salt),
        "jwt_secret": secrets.token_hex(32),
        "password_changed_at": now,
        "sessions_revoked_at": now,
      }
    )


def settings_info(store, config):
  profile = store.profile()
  metadata = (profile or {}).get("nfi_live_account", {})
  exchange = (profile or {}).get("exchange", {})
  revision = (profile or {}).get("nfi_live_revision", 0)
  status = store.status()
  return {
    "configured": profile is not None,
    "exchange": "okx",
    "revision": revision,
    "runtime_revision": config.get("nfi_live_revision", 0),
    "phase": "applying" if revision != status["revision"] else status["phase"],
    "error": status.get("error"),
    "account_label": metadata.get("label", "OKX"),
    "account_uid": metadata.get("uid"),
    "available_capital": (profile or {}).get("available_capital"),
    "credentials_configured": all(exchange.get(k) for k in ("key", "secret", "password")),
    "updated_at": metadata.get("updated_at"),
    "recipe_revision": (profile or {}).get("nfi_recipe_revision"),
    "state": str(get_rpc_optional()._freqtrade.state) if get_rpc_optional() else "unconfigured",
    "database": store.database_counts(),
  }


def save_settings(store, config, manager, payload):
  with store.exclusive():
    verify_password(manager, payload.current_password)
    require_stopped()
    existing = store.profile()
    if payload.revision != store.revision():
      raise LiveError("live_revision_conflict", 409)
    credentials = resolve_credentials(payload, (existing or {}).get("exchange"))
    transport = config.get("exchange", {}).get("ccxt_config", {})
    balance = check_connection(credentials, transport)
    counts = store.database_counts()
    if existing and counts["trades"]:
      previous_uid = existing.get("nfi_live_account", {}).get("uid")
      if not previous_uid:
        previous_uid = check_connection(existing["exchange"], transport)["uid"]
      if previous_uid != balance["uid"]:
        raise LiveError("live_account_has_history", 409)
    if existing and (counts["open_trades"] or counts["open_orders"]):
      if payload.available_capital != existing["available_capital"]:
        raise LiveError("live_capital_has_positions", 409)
    if balance["free"] < payload.available_capital and not counts["open_trades"]:
      raise LiveError("live_insufficient_balance")
    require_stopped()
    if existing:
      profile = deepcopy(existing)
      profile["available_capital"] = payload.available_capital
    else:
      mode = rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS
      base = rapidjson.loads((store.source / "configs/exampleconfig.json").read_text(), parse_mode=mode)
      blacklist = rapidjson.loads((store.source / "configs/blacklist-okx.json").read_text(), parse_mode=mode)[
        "exchange"
      ]["pair_blacklist"]
      from .recipe import initial_document

      document, live_draft = initial_document(store)
      profile = build_config(base, blacklist, document, payload.available_capital)
      if live_draft:
        profile["nfi_live_recipe_revision"] = document["revision"]
      strategy_dir = store.directory / "strategies"
      strategy_dir.mkdir(exist_ok=True)
      target = strategy_dir / "NostalgiaForInfinityX8.py"
      if not target.exists():
        shutil.copyfile(store.source / "NostalgiaForInfinityX8.py", target)
    profile["exchange"].update(credentials)
    profile["api_server"].update(
      username=config["api_server"]["username"], password=secrets.token_hex(32), jwt_secret_key=secrets.token_hex(32)
    )
    profile.update(initial_state="stopped", nfi_live_revision=payload.revision + 1)
    profile["nfi_live_account"] = {
      "label": payload.account_label,
      "uid": balance["uid"],
      "updated_at": datetime.now(UTC).isoformat(),
    }
    if existing:
      atomic_json(store.directory / ".nfi-live-previous.json", existing)
    atomic_json(store.profile_path, profile)
    return {"saved": True, "revision": profile["nfi_live_revision"], "balance": balance, "state": "stopped"}


def protect_trading_loop():
  from freqtrade.freqtradebot import FreqtradeBot

  original = FreqtradeBot.process
  if getattr(original, "_nfi_live_guard", False):
    return

  def process(bot):
    if os.environ.get("NFI_RECIPE_ROLE") != "live":
      return original(bot)
    with CONTROL_LOCK:
      return original(bot)

  process._nfi_live_guard = True
  FreqtradeBot.process = process


def configure_live_api(app, config):
  if os.environ.get("NFI_RECIPE_ROLE") != "live":
    return
  protect_trading_loop()
  store = LiveStore(config["user_data_dir"])
  public = APIRouter(prefix="/api/v1/live", route_class=SecretRoute)
  router = APIRouter(
    prefix="/api/v1/live-settings", route_class=SecretRoute, dependencies=[Depends(api_auth.http_basic_or_jwt_token)]
  )

  @public.get("/setup-status")
  def setup_status(manager: Annotated[AccountManager, Depends(account_manager)]):
    return {"required": manager.state is None}

  @public.post("/setup")
  def setup(body: SetupAccount, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    same_origin(request, local=True)
    initialize_account(store, manager, body)
    return {"success": True}

  @public.get("/runtime-ready")
  def ready():
    rpc = get_rpc_optional()
    return {"ready": bool(rpc and hasattr(rpc._freqtrade, "_measure_execution"))}

  @router.get("")
  def info():
    return settings_info(store, config)

  @router.post("/check")
  def check(body: Credentials, request: Request):
    same_origin(request)
    with CONTROL_LOCK:
      existing = store.profile()
      keys = resolve_credentials(body, (existing or {}).get("exchange"))
    return check_connection(keys, config.get("exchange", {}).get("ccxt_config", {}))

  @router.put("")
  def save(body: SaveSettings, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    same_origin(request)
    return save_settings(store, config, manager, body)

  @router.post("/reload")
  def reload(body: ReloadSettings, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    same_origin(request)
    with store.exclusive():
      verify_password(manager, body.current_password)
      require_stopped()
      if not store.profile():
        raise LiveError("live_credentials_required")
      # A same-revision reload must block Start before the supervisor replaces its worker.
      store.write_status("applying", store.revision())
      store.request_reload()
    return {"status": "reloading", "state": "stopped"}

  controls = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

  @controls.get("/show_config")
  def show_config():
    from freqtrade.rpc.api_server.api_v1 import API_VERSION

    rpc = get_rpc_optional()
    state = rpc._freqtrade.state if rpc else State.STOPPED
    version = rpc._freqtrade.strategy.version() if rpc else None
    result = RPC._rpc_show_config(config, state, version)
    result.update(
      api_version=API_VERSION, nfi_live_management=True, nfi_live_configured=store.profile() is not None, dry_run=False
    )
    return result

  def control(rpc, action):
    with CONTROL_LOCK:
      status = store.status()
      if (
        status["phase"] != "ready"
        or config.get("nfi_live_revision") != store.revision()
        or not hasattr(rpc._freqtrade, "_measure_execution")
      ):
        raise LiveError("live_apply_pending", 409)
      return action()

  @controls.post("/start")
  def start(rpc: Annotated[RPC, Depends(get_rpc)]):
    return control(rpc, rpc._rpc_start)

  @controls.post("/pause")
  def pause(rpc: Annotated[RPC, Depends(get_rpc)]):
    return control(rpc, rpc._rpc_pause)

  async def live_error(_request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status, content={"detail": exc.code})

  app.add_exception_handler(LiveError, live_error)
  app.include_router(public)
  app.include_router(router)
  app.include_router(controls)
  from .recipe import configure_live_recipe_api

  configure_live_recipe_api(app, config, store)
