"""Exercise real authentication routes with a fake clock, never production credentials."""

import base64
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api
from nfi_account.attempts import AttemptGuard
from nfi_account.credentials import AccountError


class PasswordFreezeTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.password = "fixture-freeze-password"
    self.clock = 1000000.0
    self.config = {
      "user_data_dir": self.directory,
      "dry_run": True,
      "runmode": "dry_run",
      "api_server": {
        "username": "paper",
        "password": self.password,
        "jwt_secret_key": "fixture-freeze-only-signing-secret-32-bytes",
      },
    }
    self.app, self.manager, self.client = self.make_app()
    response = self.login()
    self.token = response.json()["access_token"]
    self.refresh = response.json()["refresh_token"]
    self.bearer = {"Authorization": "Bearer " + self.token}

  def make_app(self):
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      manager = configure_account_api(app, self.config)
    manager.attempts.now = lambda: self.clock
    app.include_router(api_auth.router_login, prefix="/api/v1")

    @app.get("/api/v1/protected", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])
    def protected():
      return {"ok": True}

    return app, manager, TestClient(app)

  def basic(self, username, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()}

  def login(self, password=None, username="paper", client=None, **kwargs):
    return (client or self.client).post(
      "/api/v1/token/login", headers=self.basic(username, self.password if password is None else password), **kwargs
    )

  def change(self, password="incorrect"):
    return self.client.post(
      "/api/v1/account/password",
      headers=self.bearer,
      json={"current_password": password, "new_password": "fixture-new-password"},
    )

  def assert_frozen(self, response, seconds=300):
    self.assertEqual(response.status_code, 429, response.text)
    self.assertEqual(response.json(), {"detail": "account_rate_limited", "retry_after": seconds})
    self.assertEqual(response.headers["Retry-After"], str(seconds))
    self.assertNotIn(self.password, response.text)

  def test_fifth_failure_freezes_even_the_correct_password_and_expires_from_last_failure(self):
    for _ in range(4):
      self.assertEqual(self.login("wrong-password").status_code, 401)
      self.clock += 30
    self.assert_frozen(self.login("wrong-password"))
    self.clock += 70
    with patch.object(self.manager, "verify", side_effect=AssertionError("Frozen requests must not hash passwords")):
      self.assert_frozen(self.login(), 230)
    self.clock += 229
    self.assert_frozen(self.login(), 1)
    self.clock += 1
    self.assertEqual(self.login().status_code, 200)
    self.assertEqual(self.manager.attempts.remaining(), 0)

  def test_failed_login_and_settings_password_share_one_counter_and_all_routes_return_retry_after(self):
    self.assertEqual(self.login("wrong").status_code, 401)
    self.assertEqual(self.change().status_code, 400)
    response = self.client.put(
      "/api/v1/startup-settings",
      headers=self.bearer,
      json={"auto_start": False, "revision": 0, "current_password": "wrong"},
    )
    self.assertEqual(response.status_code, 400)
    response = self.client.put(
      "/api/v1/bark-settings", headers=self.bearer, json={"revision": 0, "current_password": "wrong"}
    )
    self.assertEqual(response.status_code, 400)
    self.assert_frozen(self.change())
    self.assert_frozen(self.login())
    self.assert_frozen(
      self.client.put(
        "/api/v1/startup-settings",
        headers=self.bearer,
        json={"auto_start": True, "revision": 0, "current_password": self.password},
      )
    )
    self.assert_frozen(
      self.client.post(
        "/api/v1/bark-settings/test", headers=self.bearer, json={"revision": 0, "current_password": self.password}
      )
    )
    self.assertFalse((self.directory / ".nfi-startup.json").exists())
    self.assertFalse((self.directory / ".nfi-bark.json").exists())
    # A password freeze affects verification, never revokes existing JWTs or stops trading.
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.bearer).status_code, 200)
    self.assertEqual(
      self.client.post("/api/v1/token/refresh", headers={"Authorization": "Bearer " + self.refresh}).status_code, 200
    )
    profile = self.client.get("/api/v1/account", headers=self.bearer).json()
    self.assertEqual(profile["password_protection"]["retry_after"], 300)
    self.assertFalse(self.manager.path.exists())

  def test_counter_survives_restart_username_rotation_and_spoofed_forwarded_ips(self):
    for index in range(4):
      self.assertEqual(self.login("wrong", username=f"unknown-{index}").status_code, 401)
    app, manager, restarted = self.make_app()
    self.assert_frozen(self.login("wrong", username="another-user", client=restarted))
    self.clock += 60
    self.assert_frozen(self.login(client=restarted), 240)
    response = restarted.post(
      "/api/v1/token/login",
      headers={**self.basic("paper", self.password), "X-Forwarded-For": "203.0.113.99", "X-Real-IP": "198.51.100.9"},
    )
    self.assert_frozen(response, 240)
    data = manager.attempts.path.read_text()
    self.assertNotIn("unknown-", data)
    self.assertNotIn(self.password, data)
    self.assertNotIn("203.0.113", data)
    self.assertEqual(manager.attempts.path.stat().st_mode & 0o777, 0o600)

  def test_http_basic_on_protected_routes_and_malformed_headers_cannot_bypass_the_counter(self):
    malformed = ("Basic ?invalid", "Basic", "Basic " + base64.b64encode(b"\xff").decode())
    for header in malformed:
      self.assertEqual(self.client.post("/api/v1/token/login", headers={"Authorization": header}).status_code, 401)
    response = self.client.get("/api/v1/protected", headers=self.basic("paper", "wrong"))
    self.assertEqual(response.status_code, 401)
    self.assert_frozen(self.client.get("/api/v1/protected", headers=self.basic("other", "wrong")))
    self.assert_frozen(self.client.get("/api/v1/protected", headers=self.basic("paper", self.password)))
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.bearer).status_code, 200)

  def test_success_resets_consecutive_failures_and_expired_window_discards_old_failures(self):
    for _ in range(4):
      self.assertEqual(self.login("wrong").status_code, 401)
    self.assertEqual(self.login().status_code, 200)
    for _ in range(4):
      self.assertEqual(self.change().status_code, 400)
    self.clock += 301
    self.assertEqual(self.change().status_code, 400)
    self.assertEqual(self.change(self.password).status_code, 200)

  def test_corrupt_symlinked_or_unwritable_guard_fails_closed_without_exposing_secrets(self):
    path = self.manager.attempts.path
    for data in ("[]", "{invalid", '{"version": 1, "scopes": {"password": {"failures": ["secret"]}}}'):
      path.write_text(data)
      response = self.login()
      self.assertEqual(response.status_code, 503)
      self.assertEqual(response.json()["detail"], "account_guard_unavailable")
      self.assertNotIn(self.password, response.text)
    path.unlink()
    target = self.directory / "private.json"
    target.write_text('{"version":1,"scopes":{}}')
    path.symlink_to(target)
    self.assertEqual(self.login().status_code, 503)
    path.unlink()
    with patch("nfi_account.attempts.os.replace", side_effect=OSError("secret fixture disk failure")):
      self.assertEqual(self.login("wrong").status_code, 503)
    self.assertEqual(list(self.directory.glob(".nfi-auth-????????")), [])
    self.assertEqual(self.login().status_code, 200)

  def test_parallel_managers_share_atomic_failure_counts(self):
    guards = [AttemptGuard(self.directory, now=lambda: self.clock) for _ in range(20)]
    checks = []

    def attempt(guard):
      try:
        return guard.verify("password", lambda: checks.append(True) or False)
      except AccountError as exc:
        return exc.status

    with ThreadPoolExecutor(max_workers=8) as pool:
      results = list(pool.map(attempt, guards))
    self.assertEqual(len(checks), 5)
    self.assertEqual(results.count(False), 4)
    self.assertEqual(results.count(429), 16)
    self.assertEqual(self.manager.attempts.remaining(), 300)

  def test_paper_live_and_setup_counters_are_independent(self):
    live = AttemptGuard(self.directory / "live", now=lambda: self.clock)
    for index in range(5):
      try:
        self.manager.attempts.verify("password", lambda: False)
      except AccountError:
        self.assertEqual(index, 4)
    self.assertTrue(live.verify("password", lambda: True))
    self.assertTrue(self.manager.attempts.verify("setup", lambda: True))
    self.assertEqual(self.manager.attempts.remaining(), 300)
