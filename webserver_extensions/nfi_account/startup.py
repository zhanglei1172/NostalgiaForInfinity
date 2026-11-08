"""Persist a per-bot startup preference and apply it only to a fresh worker."""

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from freqtrade.rpc.api_server import api_auth
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .credentials import AccountError, AccountManager
from .origin import is_same_origin

LOCK = threading.RLock()


def private_document(path):
  path = Path(path)
  if path.is_symlink():
    raise ValueError("Invalid settings file")
  if not path.exists():
    return None
  if path.stat().st_size > 2 * 1024 * 1024:
    raise ValueError("Invalid settings file")
  return json.loads(path.read_text())


class StartupStore:
  def __init__(self, directory):
    self.directory = Path(directory)
    self.path = self.directory / ".nfi-startup.json"

  def read(self):
    try:
      data = private_document(self.path)
      if data is None:
        return {"schema_version": 1, "auto_start": False, "revision": 0, "updated_at": None}
      if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or type(data.get("auto_start")) is not bool
        or type(data.get("revision")) is not int
        or data["revision"] < 1
        or not isinstance(data.get("updated_at"), str)
      ):
        raise ValueError("Invalid startup settings")
      return {key: data[key] for key in ("schema_version", "auto_start", "revision", "updated_at")}
    except (OSError, ValueError, TypeError, AttributeError):
      raise AccountError("startup_storage_unavailable", 503) from None

  @contextmanager
  def exclusive(self):
    with LOCK:
      self.directory.mkdir(parents=True, exist_ok=True)
      fd = os.open(self.directory / ".nfi-startup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
      try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

  def save(self, auto_start, revision):
    temporary = None
    try:
      with self.exclusive():
        if revision != self.read()["revision"]:
          raise AccountError("startup_revision_conflict", 409)
        data = {
          "schema_version": 1,
          "auto_start": auto_start,
          "revision": revision + 1,
          "updated_at": datetime.now(UTC).isoformat(),
        }
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".startup-", delete=False) as stream:
          temporary = Path(stream.name)
          os.fchmod(stream.fileno(), 0o600)
          json.dump(data, stream)
          stream.flush()
          os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        return data
    except OSError:
      raise AccountError("startup_storage_unavailable", 503) from None
    finally:
      if temporary:
        temporary.unlink(missing_ok=True)


def live_profile(config):
  directory = Path(config["user_data_dir"])
  profile = private_document(directory / "live-profile.json")
  if not profile or not (directory / ".nfi-account.json").is_file():
    return None
  if (
    profile.get("dry_run") is not False
    or not profile.get("nfi_live_revision")
    or profile["nfi_live_revision"] != config.get("nfi_live_revision")
    or not all(profile.get("exchange", {}).get(key) for key in ("key", "secret", "password"))
  ):
    return None
  return profile


def can_enable(config, role):
  if role == "paper":
    return config.get("dry_run") is True and str(config.get("runmode")) == "dry_run"
  try:
    profile = live_profile(config)
    status = private_document(Path(config["user_data_dir"]) / ".nfi-live-status.json") or {}
    return bool(profile and status.get("phase") == "ready" and status.get("revision") == profile["nfi_live_revision"])
  except (OSError, ValueError, TypeError, AttributeError):
    return False


def apply_startup_policy(config, reconfig=False):
  """Worker hook, after env/CLI parsing and before FreqtradeBot is constructed."""
  role = os.environ.get("NFI_RECIPE_ROLE")
  if role not in ("paper", "live"):
    return
  config["initial_state"] = "stopped"
  if reconfig:
    return
  try:
    if role == "paper":
      eligible = config.get("dry_run") is True and str(config.get("runmode")) == "dry_run"
    else:
      eligible = (
        os.environ.get("NFI_STARTUP_AUTOSTART_ALLOWED") == "1"
        and config.get("dry_run") is False
        and live_profile(config) is not None
      )
    if eligible and StartupStore(config["user_data_dir"]).read()["auto_start"]:
      config["initial_state"] = "running"
  except (AccountError, OSError, ValueError, TypeError, AttributeError):
    # Missing, damaged or unreadable preferences must never opt a bot into trading.
    pass


class SaveStartup(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  auto_start: bool
  revision: int = Field(ge=0)
  current_password: SecretStr


def configure_startup_api(app, config):
  from . import SecretRoute, account_manager

  role = os.environ.get("NFI_RECIPE_ROLE")
  if role not in ("paper", "live"):
    return
  store = StartupStore(config["user_data_dir"])
  router = APIRouter(
    prefix="/api/v1/startup-settings",
    route_class=SecretRoute,
    dependencies=[Depends(api_auth.http_basic_or_jwt_token)],
  )

  def info():
    return {**store.read(), "role": role, "can_enable": can_enable(config, role)}

  @router.get("")
  def get_settings():
    return info()

  @router.put("")
  def save_settings(body: SaveStartup, request: Request, manager: Annotated[AccountManager, Depends(account_manager)]):
    if not is_same_origin(request):
      raise HTTPException(403, detail="startup_origin_rejected")
    with manager.lock:
      manager._verify_current(body.current_password.get_secret_value())
    if body.auto_start and not can_enable(config, role):
      raise AccountError("startup_live_not_ready", 409)
    store.save(body.auto_start, body.revision)
    return info()

  app.include_router(router)
