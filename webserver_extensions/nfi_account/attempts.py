"""Bounded, persistent failure counters shared across processes and API entry points."""

import fcntl
import json
import math
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

MAX_FAILURES = 5
WINDOW_SECONDS = 300
FREEZE_SECONDS = 300
SCOPES = ("password", "setup")
LOCK = threading.RLock()


class AttemptGuard:
  def __init__(self, directory, now=None):
    self.directory = Path(directory)
    self.path = self.directory / ".nfi-auth-guard.json"
    self.now = now or time.time

  @contextmanager
  def exclusive(self):
    from .credentials import AccountError

    with LOCK:
      try:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / ".nfi-auth-guard.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
          fcntl.flock(fd, fcntl.LOCK_EX)
          yield
        finally:
          fcntl.flock(fd, fcntl.LOCK_UN)
          os.close(fd)
      except OSError:
        raise AccountError("account_guard_unavailable", 503) from None

  def read(self):
    from .credentials import AccountError

    try:
      if self.path.is_symlink():
        raise ValueError()
      if not self.path.exists():
        return {"version": 1, "scopes": {}}
      if self.path.stat().st_size > 8192:
        raise ValueError()
      data = json.loads(self.path.read_text())
      if data["version"] != 1 or not isinstance(data["scopes"], dict):
        raise ValueError()
      for scope, state in data["scopes"].items():
        if scope not in SCOPES or not isinstance(state, dict):
          raise ValueError()
        if not isinstance(state["failures"], list) or len(state["failures"]) > MAX_FAILURES:
          raise ValueError()
        if any(
          type(value) not in (int, float) or not math.isfinite(value) or value < 0
          for value in [state["frozen_until"], *state["failures"]]
        ):
          raise ValueError()
        if len(state["failures"]) == MAX_FAILURES and not state["frozen_until"]:
          raise ValueError()
      return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
      raise AccountError("account_guard_unavailable", 503) from None

  def write(self, data):
    from .credentials import AccountError

    temporary = None
    try:
      with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".nfi-auth-", delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.path)
    except OSError:
      raise AccountError("account_guard_unavailable", 503) from None
    finally:
      if temporary:
        temporary.unlink(missing_ok=True)

  def remaining(self, scope="password"):
    with self.exclusive():
      state = self.read()["scopes"].get(scope, {})
      return max(0, math.ceil(state.get("frozen_until", 0) - self.now()))

  def verify(self, scope, check):
    """Serialize checking and recording so concurrent attempts cannot exceed the limit."""
    from .credentials import AccountError

    if scope not in SCOPES:
      raise ValueError("Unsupported verification scope")
    with self.exclusive():
      data = self.read()
      previous = data["scopes"].get(scope, {"failures": [], "frozen_until": 0})
      now = self.now()
      remaining = max(0, math.ceil(previous["frozen_until"] - now))
      if remaining:
        # Blocked requests neither perform password hashing nor extend the freeze.
        raise AccountError("account_rate_limited", 429, retry_after=remaining)
      state = {
        "failures": []
        if previous["frozen_until"]
        else [at for at in previous["failures"] if at > now - WINDOW_SECONDS],
        "frozen_until": 0,
      }
      result = check()
      if result:
        state["failures"] = []
      else:
        state["failures"].append(now)
        if len(state["failures"]) >= MAX_FAILURES:
          state["frozen_until"] = now + FREEZE_SECONDS
      if state != previous:
        data["scopes"][scope] = state
        self.write(data)
      if state["frozen_until"]:
        raise AccountError("account_rate_limited", 429, retry_after=FREEZE_SECONDS)
      return result
