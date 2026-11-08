"""Offline supervisor lifecycle check using an inert child, never an exchange or order engine."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from nfi_account.startup import StartupStore
from nfi_live.storage import LiveStore, atomic_json

CHILD = r"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from nfi_account.startup import apply_startup_policy

kind = sys.argv[1]
config = json.loads(Path(sys.argv[sys.argv.index("--config") + 1]).read_text())
config["user_data_dir"] = os.environ["NFI_LIVE_DIR"]
config["runmode"] = "live" if kind == "trade" else "webserver"
apply_startup_policy(config)
event = {"kind": kind, "allowed": os.environ.get("NFI_STARTUP_AUTOSTART_ALLOWED"),
         "state": config["initial_state"]}
with open(os.environ["NFI_SMOKE_EVENTS"], "a") as stream:
  stream.write(json.dumps(event) + "\n")

class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
    body = json.dumps({"ready": True, "status": "pong"}).encode()
    self.send_response(200)
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)
  def log_message(self, *args):
    pass

HTTPServer.allow_reuse_address = True
HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
"""


def wait_until(predicate):
  deadline = time.monotonic() + 20
  while time.monotonic() < deadline:
    if predicate():
      return
    time.sleep(0.1)
  raise AssertionError("Supervisor did not reach the expected startup state")


def stop(process):
  if process and process.poll() is None:
    process.terminate()
    process.wait(timeout=10)


def main():
  with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    store = LiveStore(root / "live")
    store.ensure_bootstrap()
    # These fake credentials never reach an exchange: the child only serves local readiness.
    profile = {
      "dry_run": False,
      "nfi_live_revision": 1,
      "exchange": {"key": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"},
      "initial_state": "stopped",
    }
    atomic_json(store.profile_path, profile)
    atomic_json(store.directory / ".nfi-account.json", {})
    preferences = StartupStore(store.directory)
    preferences.save(True, 0)
    executable = root / "freqtrade"
    executable.write_text(f"#!{sys.executable}\n" + CHILD)
    executable.chmod(0o700)
    events_path = root / "events.jsonl"
    env = {
      **os.environ,
      "PATH": str(root) + os.pathsep + os.environ["PATH"],
      "NFI_RECIPE_ROLE": "live",
      "NFI_LIVE_DIR": str(store.directory),
      "NFI_SMOKE_EVENTS": str(events_path),
    }

    def events():
      return [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []

    def expect_event(number, kind, allowed, state):
      wait_until(lambda: len(events()) >= number)
      assert events()[number - 1] == {"kind": kind, "allowed": allowed, "state": state}
      wait_until(lambda: store.status()["phase"] == ("ready" if kind == "trade" else "setup"))

    process = None
    with (root / "supervisor.log").open("w") as log:
      try:
        process = subprocess.Popen([sys.executable, "-m", "nfi_live"], env=env, stdout=log, stderr=log)
        expect_event(1, "trade", "1", "running")

        store.request_reload()
        expect_event(2, "trade", "0", "stopped")
        profile["nfi_live_revision"] = 2
        atomic_json(store.profile_path, profile)
        expect_event(3, "trade", "0", "stopped")

        stop(process)
        process = subprocess.Popen([sys.executable, "-m", "nfi_live"], env=env, stdout=log, stderr=log)
        expect_event(4, "trade", "1", "running")

        stop(process)
        preferences.save(False, 1)
        process = subprocess.Popen([sys.executable, "-m", "nfi_live"], env=env, stdout=log, stderr=log)
        expect_event(5, "trade", "1", "stopped")

        stop(process)
        preferences.save(True, 2)
        store.profile_path.unlink()
        process = subprocess.Popen([sys.executable, "-m", "nfi_live"], env=env, stdout=log, stderr=log)
        expect_event(6, "webserver", "0", "stopped")
        atomic_json(store.profile_path, profile)
        expect_event(7, "trade", "0", "stopped")
      finally:
        stop(process)
    print("PASS: supervisor boot on/off, parent restart, reload/save stopped, and unconfigured management isolation")


if __name__ == "__main__":
  main()
