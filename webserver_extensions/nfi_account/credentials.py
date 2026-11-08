"""Persistent credentials for the single Freqtrade administrator account."""

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


class AccountError(Exception):
  def __init__(self, code: str, status: int = 400, retry_after: int | None = None):
    super().__init__(code)
    self.code = code
    self.status = status
    self.retry_after = retry_after


def password_hash(password: str, salt: str) -> str:
  return hashlib.scrypt(
    password.encode("utf-8"), salt=bytes.fromhex(salt), n=32768, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024
  ).hex()


def equal(left: str, right: str) -> bool:
  return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class AccountManager:
  def __init__(self, config: dict):
    self.api_config = config["api_server"]
    self.path = Path(config["user_data_dir"]) / ".nfi-account.json"
    self.lock = threading.RLock()
    self.state = None
    from .attempts import AttemptGuard

    self.attempts = AttemptGuard(self.path.parent)
    self.websockets = set()
    if self.path.exists() or self.path.is_symlink():
      if self.path.is_symlink() or self.path.stat().st_size > 8192:
        raise RuntimeError("Invalid NFI account credential file")
      try:
        state = json.loads(self.path.read_text())
        valid = (
          state["version"] == 1
          and isinstance(state["username"], str)
          and bool(state["username"])
          and len(bytes.fromhex(state["salt"])) == 16
          and len(bytes.fromhex(state["password_hash"])) == 64
          and len(bytes.fromhex(state["jwt_secret"])) == 32
          and (state["password_changed_at"] is None or isinstance(state["password_changed_at"], str))
          and isinstance(state["sessions_revoked_at"], str)
        )
        if not valid:
          raise ValueError("Invalid credential structure")
      except (ValueError, TypeError, KeyError, AssertionError) as exc:
        raise RuntimeError("Invalid NFI account credential file") from exc
      self._activate(state)

  def _activate(self, state):
    self.state = state
    self.api_config["username"] = state["username"]
    self.api_config["jwt_secret_key"] = state["jwt_secret"]

  @property
  def generation(self):
    return self.api_config["jwt_secret_key"]

  def verify(self, username: str, password: str) -> bool:
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
      return False
    with self.lock:
      if not equal(username, self.api_config.get("username", "")):
        return False
      if self.state:
        return hmac.compare_digest(password_hash(password, self.state["salt"]), self.state["password_hash"])
      return equal(password, self.api_config.get("password", ""))

  def authenticate(self, username: str, password: str):
    with self.lock:
      return self.attempts.verify("password", lambda: self.verify(username, password))

  def _verify_current(self, current: str):
    if not self.authenticate(self.api_config["username"], current):
      raise AccountError("account_incorrect_password")

  def _persist(self, state):
    temporary = None
    try:
      with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=".nfi-account-", suffix=".tmp", dir=self.path.parent, delete=False
      ) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        json.dump(state, stream)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.path)
    except OSError as exc:
      raise AccountError("account_storage_unavailable", 503) from exc
    finally:
      if temporary:
        temporary.unlink(missing_ok=True)
    self._activate(state)

  def change_password(self, current: str, new: str):
    with self.lock:
      self._verify_current(current)
      if not MIN_PASSWORD_LENGTH <= len(new) <= MAX_PASSWORD_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in new):
        raise AccountError("account_invalid_password")
      if equal(current, new):
        raise AccountError("account_password_unchanged")
      now = datetime.now(UTC).isoformat()
      salt = secrets.token_hex(16)
      self._persist(
        {
          "version": 1,
          "username": self.api_config["username"],
          "salt": salt,
          "password_hash": password_hash(new, salt),
          "jwt_secret": secrets.token_hex(32),
          "password_changed_at": now,
          "sessions_revoked_at": now,
        }
      )

  def revoke_sessions(self, current: str):
    with self.lock:
      self._verify_current(current)
      if self.state:
        state = dict(self.state)
      else:
        salt = secrets.token_hex(16)
        state = {
          "version": 1,
          "username": self.api_config["username"],
          "salt": salt,
          "password_hash": password_hash(current, salt),
          "password_changed_at": None,
        }
      state.update(jwt_secret=secrets.token_hex(32), sessions_revoked_at=datetime.now(UTC).isoformat())
      self._persist(state)

  async def close_browser_sessions(self):
    connections = list(self.websockets)
    self.websockets.clear()
    for send in connections:
      try:
        await send({"type": "websocket.close", "code": 1008})
      except (RuntimeError, OSError):
        pass
