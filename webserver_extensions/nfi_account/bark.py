"""Private per-bot Bark settings and a monitor owned by the API lifespan."""

import asyncio
import fcntl
import json
import math
import os
import tempfile
import threading
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, Request
from freqtrade.rpc.api_server import api_auth
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .credentials import AccountError, AccountManager
from .origin import is_same_origin
from .startup import private_document

LOCK = threading.RLock()
INTERVAL_SECONDS = 60
RETRY_SECONDS = 300
EVENTS = ("profit", "loss", "state")


def stamp():
  return datetime.now(UTC).isoformat()


class Rules(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
  enabled: bool = False
  profit_enabled: bool = True
  profit_threshold_pct: float = Field(default=5.0, ge=0.01, le=100000)
  loss_enabled: bool = True
  loss_threshold_pct: float = Field(default=3.0, ge=0.01, le=100)
  state_enabled: bool = False
  cooldown_minutes: int = Field(default=60, ge=5, le=1440)


class SaveBark(Rules):
  revision: int = Field(ge=0)
  current_password: SecretStr
  # Blank retains the stored destination. Clearing it is a separate explicit action.
  destination: SecretStr = SecretStr("")
  clear_destination: bool = False


class TestBark(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  revision: int = Field(ge=0)
  current_password: SecretStr


def destination_parts(value):
  """Accept the app's full push URL, send its device key only in a POST body."""
  try:
    if len(value) > 2048 or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
      raise ValueError()
    parts = urlsplit(value)
    prefix, key = parts.path.rstrip("/").rsplit("/", 1)
    if (
      parts.scheme not in ("https", "http")
      or not parts.hostname
      or parts.username is not None
      or parts.password is not None
      or parts.query
      or parts.fragment
      or not key
      or not parts.port
      and parts.netloc.endswith(":")
      or any(segment in (".", "..") for segment in unquote(parts.path).split("/"))
      or any(ord(char) < 32 for char in unquote(parts.path))
    ):
      raise ValueError()
    return urlunsplit((parts.scheme, parts.netloc, prefix + "/push", "", "")), unquote(key)
  except (ValueError, AttributeError):
    raise AccountError("bark_invalid_destination") from None


def send_bark(destination, title, body, role):
  endpoint, device_key = destination_parts(destination)
  try:
    # Do not inherit host proxies or follow a redirect carrying notification content.
    with httpx.Client(timeout=8, trust_env=False, follow_redirects=False) as client:
      response = client.post(
        endpoint,
        json={"device_key": device_key, "title": title, "body": body, "group": f"NFI-{role}", "level": "active"},
      )
      if response.status_code != 200 or response.json().get("code") != 200:
        raise ValueError()
  except (httpx.HTTPError, ValueError, AttributeError):
    # Never expose the provider response, destination, key or a raw network exception.
    raise AccountError("bark_delivery_failed", 502) from None


def empty_runtime():
  return {"rules": {}, "history": [], "last_checked_at": None, "roi_pct": None, "bot_state": None, "error": None}


class BarkStore:
  def __init__(self, directory):
    self.directory = Path(directory)
    self.path = self.directory / ".nfi-bark.json"

  @contextmanager
  def exclusive(self):
    with LOCK:
      try:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / ".nfi-bark.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
          fcntl.flock(fd, fcntl.LOCK_EX)
          yield
        finally:
          fcntl.flock(fd, fcntl.LOCK_UN)
          os.close(fd)
      except OSError:
        raise AccountError("bark_storage_unavailable", 503) from None

  def read(self):
    try:
      data = private_document(self.path)
      if data is None:
        return {
          "schema_version": 1,
          "revision": 0,
          "updated_at": None,
          "destination": "",
          "settings": Rules().model_dump(),
          "runtime": empty_runtime(),
        }
      if (
        data["schema_version"] != 1
        or type(data["revision"]) is not int
        or data["revision"] < 1
        or not isinstance(data["destination"], str)
        or not isinstance(data["updated_at"], str)
      ):
        raise ValueError()
      data["settings"] = Rules.model_validate(data["settings"]).model_dump()
      if data["destination"]:
        destination_parts(data["destination"])
      runtime = data["runtime"]
      if (
        not isinstance(runtime, dict)
        or not isinstance(runtime["history"], list)
        or not isinstance(runtime["rules"], dict)
      ):
        raise ValueError()
      if (
        runtime.get("roi_pct") is not None
        and not math.isfinite(runtime["roi_pct"])
        or runtime.get("error") not in (None, "bark_bot_not_ready", "bark_metrics_unavailable")
        or runtime.get("last_checked_at") is not None
        and not isinstance(runtime["last_checked_at"], str)
        or runtime.get("bot_state") is not None
        and not isinstance(runtime["bot_state"], str)
        or len(runtime["history"]) > 20
      ):
        raise ValueError()
      for item in runtime["history"]:
        if (
          not isinstance(item, dict)
          or item.get("event") not in (*EVENTS, "test")
          or type(item.get("success")) is not bool
          or not isinstance(item.get("at"), str)
          or item.get("error") not in (None, "bark_delivery_failed")
        ):
          raise ValueError()
      # Runtime corruption must not silently reset deduplication and cause a flood.
      for name, rule in runtime["rules"].items():
        if name not in (*EVENTS, "test") or not isinstance(rule, dict):
          raise ValueError()
        if (
          type(rule.get("latched")) is not bool
          or not math.isfinite(rule["last_attempt"])
          or ("retry_at" in rule and not math.isfinite(rule["retry_at"]))
        ):
          raise ValueError()
      return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError, AccountError):
      raise AccountError("bark_storage_unavailable", 503) from None

  def write(self, data):
    temporary = None
    try:
      with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".nfi-bark-", delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.path)
    except (OSError, ValueError):
      raise AccountError("bark_storage_unavailable", 503) from None
    finally:
      if temporary:
        temporary.unlink(missing_ok=True)

  def save(self, body):
    with self.exclusive():
      data = self.read()
      if body.revision != data["revision"]:
        raise AccountError("bark_revision_conflict", 409)
      destination = body.destination.get_secret_value().strip()
      if body.clear_destination and destination:
        raise AccountError("bark_invalid_destination")
      if destination:
        destination_parts(destination)
      destination = "" if body.clear_destination else destination or data["destination"]
      settings = Rules.model_validate({key: getattr(body, key) for key in Rules.model_fields}).model_dump()
      if settings["enabled"] and (not destination or not any(settings[f"{event}_enabled"] for event in EVENTS)):
        raise AccountError("bark_missing_rule_or_destination")
      old = data["settings"]
      if destination != data["destination"] or settings["enabled"] != old["enabled"]:
        data["runtime"] = {**empty_runtime(), "history": data["runtime"]["history"]}
      else:
        for event in EVENTS:
          keys = (f"{event}_enabled", f"{event}_threshold_pct")
          if any(settings.get(key) != old.get(key) for key in keys):
            data["runtime"]["rules"].pop(event, None)
      data.update(destination=destination, settings=settings, revision=data["revision"] + 1, updated_at=stamp())
      self.write(data)
      return data


def public_settings(data, role):
  runtime = data["runtime"]
  # Explicit projection: stored secrets must never appear in API responses.
  return {
    **data["settings"],
    "revision": data["revision"],
    "updated_at": data["updated_at"],
    "role": role,
    "destination_configured": bool(data["destination"]),
    "check_interval_seconds": INTERVAL_SECONDS,
    "last_checked_at": runtime.get("last_checked_at"),
    "roi_pct": runtime.get("roi_pct"),
    "bot_state": runtime.get("bot_state"),
    "monitor_error": runtime.get("error"),
    "history": [
      {key: item.get(key) for key in ("at", "event", "success", "error")} for item in runtime["history"][-20:][::-1]
    ],
  }


def profit_snapshot():
  """Match Freqtrade's total trading P&L, including fees and partial exits."""
  from freqtrade.persistence import Trade
  from freqtrade.rpc.api_server.deps import get_rpc_optional
  from sqlalchemy import func, select

  rpc = get_rpc_optional()
  if not rpc or not hasattr(rpc._freqtrade, "_measure_execution"):
    return None
  bot = rpc._freqtrade
  try:
    Trade.rollback()
    closed = Trade.session.scalar(select(func.coalesce(func.sum(Trade.close_profit_abs), 0)).where(~Trade.is_open))
    opened = list(Trade.session.scalars(Trade.get_trades_query(Trade.is_open.is_(True))).all())
    stats = rpc._collect_trade_statistics_data(opened, bot.config["stake_currency"], "")
    total = float(closed) + sum(stats["profit_all_coin"])
    initial = float(bot.wallets.get_starting_balance())
    if not math.isfinite(total) or not math.isfinite(initial) or initial <= 0:
      raise ValueError("Unavailable profit data")
    return {"roi_pct": total / initial * 100, "bot_state": str(bot.state).lower()}
  finally:
    Trade.session.remove()


class BarkMonitor:
  def __init__(self, store, role, sample=profit_snapshot, send=send_bark, now=time.time):
    self.store, self.role, self.sample, self.send, self.now = store, role, sample, send, now

  def tick(self):
    # Keep all exchange/HTTP operations away from the trading loop and API event loop.
    try:
      with self.store.exclusive():
        before = self.store.read()
      if not before["settings"]["enabled"]:
        return
      try:
        snapshot = self.sample()
        error = None if snapshot is not None else "bark_bot_not_ready"
        if snapshot is not None and not math.isfinite(snapshot["roi_pct"]):
          raise ValueError()
      except Exception:
        snapshot, error = None, "bark_metrics_unavailable"
      pending = []
      with self.store.exclusive():
        data = self.store.read()
        if data["revision"] != before["revision"]:
          return
        settings, runtime = data["settings"], data["runtime"]
        runtime.update(last_checked_at=stamp(), error=error)
        if snapshot is not None:
          previous = runtime.get("bot_state")
          runtime.update(snapshot)
          conditions = {
            "profit": snapshot["roi_pct"] >= settings["profit_threshold_pct"],
            "loss": snapshot["roi_pct"] <= -settings["loss_threshold_pct"],
            "state": previous is not None and previous != snapshot["bot_state"],
          }
          for event, triggered in conditions.items():
            if not settings[f"{event}_enabled"]:
              continue
            rule = runtime["rules"].setdefault(event, {"latched": False, "last_attempt": 0})
            if event == "state":
              rule.setdefault("baseline", previous if previous is not None else snapshot["bot_state"])
              triggered = rule["baseline"] != snapshot["bot_state"]
            if not triggered:
              rule["latched"] = False
              rule.pop("retry_at", None)
              continue
            eligible_at = rule.get("retry_at", rule["last_attempt"] + settings["cooldown_minutes"] * 60)
            if rule["latched"] or self.now() < eligible_at:
              continue
            # Claim before sending; persisted claims survive restarts and prevent concurrent duplicates.
            rule.update(latched=True, last_attempt=self.now())
            if event == "state":
              rule["pending_state"] = snapshot["bot_state"]
            pending.append(event)
        self.store.write(data)
      for event in pending:
        with self.store.exclusive():
          current = self.store.read()
          if current["revision"] != data["revision"]:
            return
        label = "模拟盘" if self.role == "paper" else "实盘"
        names = {"profit": "收益达标", "loss": "亏损预警", "state": "机器人状态变化"}
        body = f"交易累计收益率 {snapshot['roi_pct']:+.2f}%（含持仓浮盈亏及手续费）"
        if event == "state":
          body += f"\n机器人状态：{snapshot['bot_state']}"
        else:
          body += f"\n设定阈值：{'+' if event == 'profit' else '-'}{settings[f'{event}_threshold_pct']:g}%"
        self.deliver(data, event, f"NFI {label} · {names[event]}", body)
    except Exception:
      # Notification faults must never interrupt trading or kill future monitoring ticks.
      return

  def deliver(self, data, event, title, body):
    error = None
    try:
      self.send(data["destination"], title, body, self.role)
    except Exception:
      error = "bark_delivery_failed"
    with self.store.exclusive():
      current = self.store.read()
      if current["revision"] != data["revision"]:
        return error
      runtime = current["runtime"]
      runtime["history"] = (
        runtime["history"] + [{"at": stamp(), "event": event, "success": error is None, "error": error}]
      )[-20:]
      if error and event != "test":
        # Retry failed deliveries after five minutes, without rearming successful crossings.
        runtime["rules"][event]["latched"] = False
        runtime["rules"][event]["retry_at"] = self.now() + RETRY_SECONDS
      elif event != "test":
        rule = runtime["rules"][event]
        rule.pop("retry_at", None)
        if event == "state":
          rule.update(baseline=rule.pop("pending_state"), latched=False)
      self.store.write(current)
    return error

  def test(self, revision):
    with self.store.exclusive():
      data = self.store.read()
      if revision != data["revision"]:
        raise AccountError("bark_revision_conflict", 409)
      if not data["destination"]:
        raise AccountError("bark_missing_rule_or_destination")
      rule = data["runtime"]["rules"].get("test")
      if rule and self.now() - rule["last_attempt"] < 60:
        raise AccountError("bark_test_rate_limited", 429)
      data["runtime"]["rules"]["test"] = {"latched": False, "last_attempt": self.now()}
      self.store.write(data)
    error = self.deliver(
      data,
      "test",
      f"NFI {'模拟盘' if self.role == 'paper' else '实盘'} · 测试通知",
      "Bark 通知连接测试成功。此消息不代表交易已启动。",
    )
    if error:
      raise AccountError(error, 502)


def configure_bark_api(app, config):
  from . import SecretRoute, account_manager

  role = os.environ.get("NFI_RECIPE_ROLE")
  if role not in ("paper", "live"):
    return
  store = BarkStore(config["user_data_dir"])
  monitor = BarkMonitor(store, role)
  app.state.bark_monitor = monitor
  previous_lifespan = app.router.lifespan_context

  @asynccontextmanager
  async def lifespan(application):
    async with previous_lifespan(application):

      async def run():
        while True:
          await asyncio.to_thread(monitor.tick)
          await asyncio.sleep(INTERVAL_SECONDS)

      task = asyncio.create_task(run())
      try:
        yield
      finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
          await task

  app.router.lifespan_context = lifespan
  router = APIRouter(
    prefix="/api/v1/bark-settings", route_class=SecretRoute, dependencies=[Depends(api_auth.http_basic_or_jwt_token)]
  )

  def verify(request, manager, password):
    if not is_same_origin(request):
      raise AccountError("bark_origin_rejected", 403)
    with manager.lock:
      manager._verify_current(password.get_secret_value())

  def info():
    with store.exclusive():
      return public_settings(store.read(), role)

  @router.get("")
  def get_settings():
    return info()

  @router.put("")
  def save_settings(body: SaveBark, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    verify(request, manager, body.current_password)
    store.save(body)
    return info()

  @router.post("/test")
  def test_notification(
    body: TestBark, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]
  ):
    verify(request, manager, body.current_password)
    monitor.test(body.revision)
    return info()

  app.include_router(router)
