"""Supervise Web-managed live workers; auto-start is eligible only at container boot."""

import json
import os
import signal
import subprocess
import threading
import time
from urllib.parse import quote
from urllib.request import urlopen

from .storage import LiveStore


def child_command(store, trading):
  common = ["--userdir", str(store.directory)]
  if trading:
    return [
      "freqtrade",
      "trade",
      "--config",
      str(store.profile_path),
      "--strategy-path",
      str(store.directory / "strategies"),
      "--db-url",
      f"sqlite:///{store.directory}/trades-live.sqlite",
      *common,
    ]
  return ["freqtrade", "webserver", "--config", str(store.bootstrap_path), *common]


def child_environment(trading, allow_startup=False):
  env = os.environ.copy()
  private = (
    "FREQTRADE__EXCHANGE__KEY",
    "FREQTRADE__EXCHANGE__SECRET",
    "FREQTRADE__EXCHANGE__PASSWORD",
    "FREQTRADE__AVAILABLE_CAPITAL",
    "FREQTRADE__DRY_RUN_WALLET",
    "FREQTRADE__TRADABLE_BALANCE_RATIO",
  )
  for key in list(env):
    if key in private or key.startswith("FREQTRADE__API_SERVER__"):
      del env[key]
  env.update(
    NFI_RECIPE_ROLE="live",
    FREQTRADE__INITIAL_STATE="stopped",
    FREQTRADE__DRY_RUN="false" if trading else "true",
    NFI_STARTUP_AUTOSTART_ALLOWED="1" if trading and allow_startup else "0",
    PYTHONUNBUFFERED="1",
  )
  return env


def redactions(config):
  exchange = config.get("exchange", {})
  api = config.get("api_server", {})
  values = [exchange.get(k) for k in ("key", "secret", "password")]
  values.extend(api.get(k) for k in ("password", "jwt_secret_key"))
  return sorted(
    {variant for value in values if value for variant in (value, json.dumps(value)[1:-1], quote(value))},
    key=len,
    reverse=True,
  )


def output_logs(process, secrets):
  for line in process.stdout:
    for value in secrets:
      line = line.replace(value, "[redacted]")
    print(line, end="", flush=True)


def terminate(process):
  if process.poll() is not None:
    return
  process.terminate()
  try:
    process.wait(timeout=25)
  except subprocess.TimeoutExpired:
    process.kill()
    process.wait(timeout=5)


def ready(trading):
  path = "/api/v1/live/runtime-ready" if trading else "/api/v1/ping"
  try:
    with urlopen("http://127.0.0.1:8080" + path, timeout=0.5) as response:
      data = json.load(response)
      return data.get("ready") is True if trading else data.get("status") == "pong"
  except (OSError, ValueError):
    return False


def main():
  store = LiveStore(os.environ.get("NFI_LIVE_DIR", "/freqtrade/user_data"))
  store.ensure_bootstrap()
  store.migrate_legacy()
  stopping = threading.Event()
  for name in (signal.SIGTERM, signal.SIGINT):
    signal.signal(name, lambda _signum, _frame: stopping.set())
  process = None
  attempted = None
  failed = None
  healthy = False
  trading = False
  deadline = 0
  first_launch = True
  try:
    while not stopping.is_set():
      revision = store.revision()
      request = (revision, store.reload_nonce())
      changed = request != attempted
      # Let a successful save response reach the browser before replacing its server process.
      recent_save = store.profile_path.exists() and time.time() - store.profile_path.stat().st_mtime < 2
      if process is None or (changed and not recent_save):
        if process:
          terminate(process)
        attempted = request
        trading = revision > 0 and failed != request
        phase = "loading" if trading else "error" if failed else "setup"
        store.write_status(phase, revision, "live_start_failed" if failed else None)
        config = store.profile() if trading else store.ensure_bootstrap()
        process = subprocess.Popen(
          child_command(store, trading),
          env=child_environment(trading, allow_startup=first_launch),
          stdout=subprocess.PIPE,
          stderr=subprocess.STDOUT,
          text=True,
          bufsize=1,
        )
        first_launch = False
        threading.Thread(target=output_logs, args=(process, redactions(config)), daemon=True).start()
        healthy = False
        deadline = time.monotonic() + 120
      if process.poll() is not None or (not healthy and time.monotonic() > deadline):
        terminate(process)
        if trading:
          failed = attempted
          print("Live worker exited or failed to initialize; returning to account settings.", flush=True)
        else:
          store.write_status("error", revision, "live_management_failed")
          stopping.wait(3)
        process = None
        continue
      if not healthy and ready(trading):
        healthy = True
        if trading:
          failed = None
          store.write_status("ready", revision)
          print("Live worker ready. Initial trading state follows the saved Web startup preference.", flush=True)
      stopping.wait(0.5)
  finally:
    if process:
      terminate(process)


if __name__ == "__main__":
  main()
