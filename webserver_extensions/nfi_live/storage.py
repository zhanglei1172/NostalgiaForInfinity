"""Private, atomic storage shared by the live supervisor and authenticated API."""

import fcntl
import json
import os
import secrets
import sqlite3
import tempfile
import threading
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

CONTROL_LOCK = threading.RLock()


class LiveError(Exception):
  def __init__(self, code, status=400):
    super().__init__(code)
    self.code, self.status = code, status


def atomic_json(path, data):
  path = Path(path)
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = None
  try:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".live-", delete=False) as f:
      temporary = Path(f.name)
      os.fchmod(f.fileno(), 0o600)
      json.dump(data, f, ensure_ascii=False, allow_nan=False, indent=2)
      f.write("\n")
      f.flush()
      os.fsync(f.fileno())
    os.replace(temporary, path)
  finally:
    if temporary:
      temporary.unlink(missing_ok=True)


def read_json(path, default=None):
  path = Path(path)
  if not path.exists():
    return default
  if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
    raise LiveError("live_storage_invalid", 503)
  return json.loads(path.read_text())


class LiveStore:
  def __init__(self, directory, source=None):
    self.directory = Path(directory)
    self.source = Path(source or os.environ.get("NFI_LIVE_SOURCE", "/opt/nfi"))
    self.profile_path = self.directory / "live-profile.json"
    self.bootstrap_path = self.directory / ".nfi-bootstrap.json"
    self.status_path = self.directory / ".nfi-live-status.json"
    self.reload_path = self.directory / ".nfi-live-reload.json"

  @contextmanager
  def exclusive(self):
    with CONTROL_LOCK:
      self.directory.mkdir(parents=True, exist_ok=True)
      lock_path = self.directory / ".nfi-live.lock"
      fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
      try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

  def profile(self):
    return read_json(self.profile_path)

  def revision(self):
    return (self.profile() or {}).get("nfi_live_revision", 0)

  def status(self):
    return read_json(self.status_path, {"phase": "setup", "revision": 0, "error": None})

  def write_status(self, phase, revision=0, error=None):
    atomic_json(self.status_path, {"phase": phase, "revision": revision, "error": error})

  def request_reload(self):
    atomic_json(self.reload_path, {"nonce": secrets.token_hex(16)})

  def reload_nonce(self):
    return (read_json(self.reload_path) or {}).get("nonce")

  def database_counts(self):
    path = self.directory / "trades-live.sqlite"
    if not path.exists():
      return {"trades": 0, "open_trades": 0, "open_orders": 0}
    try:
      with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        trades, opened = db.execute("SELECT count(*), coalesce(sum(is_open), 0) FROM trades").fetchone()
        orders = db.execute("SELECT count(*) FROM orders WHERE ft_is_open = 1").fetchone()[0]
      return {"trades": trades, "open_trades": opened, "open_orders": orders}
    except sqlite3.Error:
      raise LiveError("live_database_unavailable", 503) from None

  def ensure_bootstrap(self):
    with self.exclusive():
      current = read_json(self.bootstrap_path)
      if current:
        return current
      config = {
        "dry_run": True,
        "initial_state": "stopped",
        "trading_mode": "spot",
        "margin_mode": "",
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "max_open_trades": 6,
        "timeframe": "5m",
        "bot_name": "NFI_Live_Setup",
        "exchange": {"name": "okx", "key": "", "secret": "", "password": "", "pair_whitelist": ["BTC/USDT"]},
        "pairlists": [{"method": "StaticPairList"}],
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "api_server": {
          "enabled": True,
          "listen_ip_address": "0.0.0.0",
          "listen_port": 8080,
          "username": "setup-pending",
          "password": secrets.token_hex(32),
          "jwt_secret_key": secrets.token_hex(32),
          "enable_openapi": False,
          "verbosity": "error",
          "CORS_origins": [],
        },
      }
      atomic_json(self.bootstrap_path, config)
      return config

  def migrate_legacy(self):
    """Retain existing deployments; never overwrite their original credentials or database."""
    from nfi_account.credentials import AccountManager

    with self.exclusive():
      if self.profile_path.exists():
        return
      config = read_json(self.directory / "config.json")
      credentials = read_json(self.directory / "credentials.json")
      if not config or not credentials:
        return
      if config.get("exchange", {}).get("name") != "okx" or config.get("dry_run") is not False:
        raise LiveError("live_legacy_config_invalid")
      config["exchange"].update(credentials["exchange"])
      config["api_server"].update(credentials["api_server"])
      manager = AccountManager({"api_server": config["api_server"], "user_data_dir": self.directory})
      if manager.state is None:
        manager.revoke_sessions(credentials["api_server"]["password"])
      config["api_server"].update(password=secrets.token_hex(32), jwt_secret_key=secrets.token_hex(32))
      config.update(initial_state="stopped", nfi_live_revision=1)
      config["nfi_live_account"] = {"label": "OKX", "uid": None, "updated_at": datetime.now(UTC).isoformat()}
      atomic_json(self.profile_path, config)
