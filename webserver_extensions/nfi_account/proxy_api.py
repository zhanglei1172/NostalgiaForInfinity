"""Authenticated proxy drafts, explicit stopped-worker application and public connectivity probes."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Annotated, Literal

import ccxt
import ccxt.pro
from fastapi import APIRouter, Depends, HTTPException, Request
from freqtrade.enums import State
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_rpc_optional
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .credentials import AccountError, AccountManager
from .origin import is_same_origin
from .proxy import ProxyStore, configure_client, install_redaction, public_settings, validate_settings


class DraftProxy(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  enabled: bool
  protocol: Literal["socks5h", "socks5", "http", "https"]
  host: str = Field(max_length=253)
  port: int = Field(ge=1, le=65535)
  auth_enabled: bool
  username: SecretStr = SecretStr("")
  password: SecretStr = SecretStr("")
  revision: int = Field(ge=0)
  current_password: SecretStr


class ApplyProxy(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  revision: int = Field(ge=0)
  current_password: SecretStr


def resolve_draft(body, previous):
  value = {key: getattr(body, key) for key in ("enabled", "protocol", "host", "port", "auth_enabled")}
  for field in ("username", "password"):
    value[field] = getattr(body, field).get_secret_value() or previous[field]
  try:
    return validate_settings(value)
  except (ValueError, TypeError, UnicodeError):
    raise AccountError("proxy_invalid_settings") from None


def probe_error(exc):
  if isinstance(exc, (ccxt.AuthenticationError, ccxt.PermissionDenied)):
    return "proxy_auth_failed"
  if isinstance(exc, (TimeoutError, ccxt.RequestTimeout)):
    return "proxy_timeout"
  if isinstance(exc, (ccxt.RateLimitExceeded, ccxt.DDoSProtection)):
    return "proxy_exchange_limited"
  if isinstance(exc, (ImportError, ccxt.NotSupported)):
    return "proxy_dependency_missing"
  return "proxy_connection_failed"


def probe_connection(settings):
  """Only public OKX time and BTC candles; never use account credentials or create an order."""
  install_redaction(settings)
  checks = {}
  options = {"enableRateLimit": True, "timeout": 8000, "verbose": False}
  started = time.monotonic()
  client = None
  try:
    client = configure_client(ccxt.okx(options), settings)
    client.fetch_time()
    checks["rest_sync"] = {"success": True, "latency_ms": round((time.monotonic() - started) * 1000)}
  except Exception as exc:
    checks["rest_sync"] = {"success": False, "error": probe_error(exc)}
  finally:
    if client is not None:
      client.session.close()

  async def asynchronous():
    client = configure_client(ccxt.pro.okx(options), settings)
    try:
      started = time.monotonic()
      try:
        await asyncio.wait_for(client.fetch_time(), timeout=10)
        checks["rest_async"] = {"success": True, "latency_ms": round((time.monotonic() - started) * 1000)}
      except Exception as exc:
        checks["rest_async"] = {"success": False, "error": probe_error(exc)}
      client.set_markets(
        [
          {
            "id": "BTC-USDT",
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "baseId": "BTC",
            "quoteId": "USDT",
            "type": "spot",
            "spot": True,
            "active": True,
            "contract": False,
            "precision": {"amount": 0.00000001, "price": 0.01},
            "limits": {},
          }
        ]
      )
      started = time.monotonic()
      try:
        candles = await asyncio.wait_for(client.watch_ohlcv("BTC/USDT", "5m"), timeout=12)
        if not candles:
          raise ValueError("No public candles")
        checks["websocket"] = {"success": True, "latency_ms": round((time.monotonic() - started) * 1000)}
      except Exception as exc:
        checks["websocket"] = {"success": False, "error": probe_error(exc)}
    finally:
      try:
        await asyncio.wait_for(client.close(), timeout=3)
      except Exception:
        pass

  try:
    asyncio.run(asynchronous())
  except Exception as exc:
    for name in ("rest_async", "websocket"):
      checks.setdefault(name, {"success": False, "error": probe_error(exc)})
  return {
    "success": all(check["success"] for check in checks.values()),
    "checks": checks,
    "checked_at": datetime.now(UTC).isoformat(),
  }


def apply_block(config, role):
  rpc = get_rpc_optional()
  if rpc and rpc._freqtrade.state != State.STOPPED:
    return "proxy_stop_required"
  if role == "live":
    from nfi_live.storage import LiveStore

    counts = LiveStore(config["user_data_dir"]).database_counts()
    if counts["open_trades"] or counts["open_orders"]:
      return "proxy_positions_open"
  elif rpc:
    from freqtrade.persistence import Order, Trade

    if Trade.get_open_trade_count() or Order.get_open_orders():
      return "proxy_positions_open"
  return None


def configure_proxy_api(app, config):
  import os

  from . import SecretRoute, account_manager

  role = os.environ.get("NFI_RECIPE_ROLE")
  if role not in ("paper", "live"):
    return
  store = ProxyStore(config["user_data_dir"])
  router = APIRouter(
    prefix="/api/v1/proxy-settings", route_class=SecretRoute, dependencies=[Depends(api_auth.http_basic_or_jwt_token)]
  )

  def info():
    data = store.read()
    reason = apply_block(config, role)
    return {
      "role": role,
      "revision": data["revision"],
      "settings": public_settings(data["draft"]),
      "active_revision": data["active_revision"],
      "active_enabled": data["active"]["enabled"],
      "runtime_revision": config.get("nfi_proxy_revision"),
      "runtime_enabled": config.get("nfi_proxy_enabled"),
      "pending_changes": data["draft"] != data["active"],
      "updated_at": data["updated_at"],
      "applied_at": data["applied_at"],
      "can_apply": reason is None,
      "apply_block_reason": reason,
    }

  def verify(request, manager, password):
    if not is_same_origin(request):
      raise HTTPException(403, detail="proxy_origin_rejected")
    with manager.lock:
      manager._verify_current(password.get_secret_value())

  @router.get("")
  def get_settings():
    return info()

  @router.put("")
  def save(body: DraftProxy, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    verify(request, manager, body.current_password)
    before = store.read()
    store.save(resolve_draft(body, before["draft"]), body.revision)
    return info()

  @router.post("/check")
  def check(body: DraftProxy, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    verify(request, manager, body.current_password)
    with store.exclusive():
      data = store.read()
      if body.revision != data["revision"]:
        raise AccountError("proxy_revision_conflict", 409)
      settings = resolve_draft(body, data["draft"])
      if time.time() - data["last_test_at"] < 30:
        raise AccountError("proxy_test_rate_limited", 429)
      data["last_test_at"] = time.time()
      store.write(data)
    return probe_connection(settings)

  @router.post("/apply")
  def apply(body: ApplyProxy, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    from nfi_live.storage import CONTROL_LOCK, LiveStore

    verify(request, manager, body.current_password)
    with CONTROL_LOCK, store.exclusive():
      reason = apply_block(config, role)
      if reason:
        raise AccountError(reason, 409)
      data = store.read()
      if body.revision != data["revision"]:
        raise AccountError("proxy_revision_conflict", 409)
      rpc = get_rpc_optional()
      data.update(
        active=dict(data["draft"]), active_revision=data["revision"], applied_at=datetime.now(UTC).isoformat()
      )
      store.write(data)
      if role == "live":
        live = LiveStore(config["user_data_dir"])
        if live.profile():
          live.write_status("applying", live.revision())
          live.request_reload()
      elif rpc:
        rpc._freqtrade.state = State.RELOAD_CONFIG
    return {**info(), "status": "applied", "state": "stopped"}

  app.include_router(router)
  if role == "paper":
    controls = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

    @controls.post("/start")
    def start():
      if store.read()["active_revision"] != config.get("nfi_proxy_revision", 0):
        raise AccountError("proxy_apply_pending", 409)
      rpc = get_rpc_optional()
      if rpc is None:
        raise AccountError("proxy_apply_pending", 409)
      return rpc._rpc_start()

    app.include_router(controls)
