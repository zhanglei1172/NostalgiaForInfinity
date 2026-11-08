import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.enums import RunMode
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api
from nfi_account.startup import StartupStore, apply_startup_policy


class StartupTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.password = "fixture-startup-password"
    self.config = {
      "user_data_dir": self.directory,
      "dry_run": True,
      "runmode": RunMode.DRY_RUN,
      "initial_state": "stopped",
      "api_server": {"username": "paper", "password": self.password, "jwt_secret_key": "fixture-only-key"},
    }
    self.store = StartupStore(self.directory)
    self.app, self.manager, self.client = self.make_app("paper")

  def make_app(self, role):
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": role}):
      manager = configure_account_api(app, self.config)
    client = TestClient(app)
    client.auth = ("paper", self.password)
    return app, manager, client

  def save(self, enabled=True, revision=0, **changes):
    return self.client.put(
      "/api/v1/startup-settings",
      json={"auto_start": enabled, "revision": revision, "current_password": self.password, **changes},
    )

  def live(self):
    self.config.update(dry_run=False, runmode=RunMode.LIVE, nfi_live_revision=1)
    self.app, self.manager, self.client = self.make_app("live")
    self.manager.revoke_sessions(self.password)

  def ready_profile(self):
    profile = {
      "dry_run": False,
      "nfi_live_revision": 1,
      "exchange": {"key": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"},
    }
    (self.directory / "live-profile.json").write_text(json.dumps(profile))
    (self.directory / ".nfi-live-status.json").write_text(json.dumps({"phase": "ready", "revision": 1}))

  def test_default_is_off_and_requests_require_authentication(self):
    self.client.auth = None
    self.assertEqual(self.client.get("/api/v1/startup-settings").status_code, 401)
    self.client.auth = ("paper", self.password)
    result = self.client.get("/api/v1/startup-settings")
    self.assertEqual(result.status_code, 200)
    self.assertFalse(result.json()["auto_start"])
    self.assertTrue(result.json()["can_enable"])
    self.assertFalse(self.store.path.exists())
    self.assertNotIn(self.password, result.text)

  def test_preference_survives_restart_is_private_and_never_changes_the_current_state(self):
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.config["initial_state"], "stopped")
    self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
    self.assertNotIn(self.password, self.store.path.read_text())
    _, _, restarted = self.make_app("paper")
    self.assertTrue(restarted.get("/api/v1/startup-settings").json()["auto_start"])
    self.assertEqual(self.save(False, 1).status_code, 200)
    self.assertFalse(self.store.read()["auto_start"])

  def test_wrong_password_validation_and_cross_origin_cannot_enable_startup(self):
    response = self.save(current_password="fixture-wrong-password")
    self.assertEqual(response.status_code, 400)
    self.assertFalse(self.store.path.exists())
    for body in ({"auto_start": "true"}, {"extra": "secret-input"}):
      response = (
        self.save(**body)
        if "extra" in body
        else self.client.put(
          "/api/v1/startup-settings",
          json={"auto_start": "true", "revision": 0, "current_password": self.password},
        )
      )
      self.assertEqual(response.status_code, 400)
      self.assertNotIn(self.password, response.text)
      self.assertNotIn("secret-input", response.text)
    response = self.client.put(
      "/api/v1/startup-settings",
      headers={"Origin": "https://evil.test"},
      json={"auto_start": True, "revision": 0, "current_password": self.password},
    )
    self.assertEqual(response.status_code, 403)
    self.assertFalse(self.store.path.exists())

  def test_stale_writes_and_storage_errors_preserve_the_previous_preference(self):
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save(False).status_code, 409)
    with patch("nfi_account.startup.os.replace", side_effect=OSError("fixture disk failure")):
      self.assertEqual(self.save(False, 1).status_code, 503)
    self.assertTrue(self.store.read()["auto_start"])
    self.assertEqual(list(self.directory.glob(".startup-*")), [])

  def test_same_origin_browser_can_save_through_a_reverse_proxy(self):
    self.client.headers.update({"Origin": "https://console.example.test", "Sec-Fetch-Site": "same-origin"})
    self.assertEqual(self.save(False).status_code, 200)
    self.client.headers["Sec-Fetch-Site"] = "same-site"
    rejected = self.save(True, 1)
    self.assertEqual(rejected.status_code, 403)
    self.assertFalse(self.store.read()["auto_start"])

  def test_paper_boot_applies_saved_preference_but_config_reload_is_always_stopped(self):
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      self.config["initial_state"] = "running"
      apply_startup_policy(self.config)
      self.assertEqual(self.config["initial_state"], "stopped")
      self.store.save(True, 0)
      apply_startup_policy(self.config)
      self.assertEqual(self.config["initial_state"], "running")
      apply_startup_policy(self.config, reconfig=True)
      self.assertEqual(self.config["initial_state"], "stopped")
      self.store.save(False, 1)
      apply_startup_policy(self.config)
      self.assertEqual(self.config["initial_state"], "stopped")

  def test_installed_worker_hook_applies_the_preference_before_bot_creation_and_detects_reconfigure(self):
    from copy import deepcopy

    from freqtrade.worker import Worker

    self.store.save(True, 0)
    worker = Worker.__new__(Worker)
    worker._config = deepcopy(self.config)
    worker._args = {}
    with (
      patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}),
      patch("freqtrade.worker.FreqtradeBot") as bot,
      patch("freqtrade.worker.Configuration") as configuration,
    ):
      configuration.return_value.get_config.side_effect = lambda: deepcopy(self.config)
      worker._init(False)
      self.assertEqual(bot.call_args.args[0]["initial_state"], "running")
      worker._init(True)
      self.assertEqual(bot.call_args.args[0]["initial_state"], "stopped")

  def test_corrupt_or_symlinked_preferences_fail_closed(self):
    for contents in ('{"auto_start": "true"}', "[]", "{invalid json"):
      self.store.path.write_text(contents)
      with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
        self.config["initial_state"] = "running"
        apply_startup_policy(self.config)
      self.assertEqual(self.config["initial_state"], "stopped")
      self.assertEqual(self.client.get("/api/v1/startup-settings").status_code, 503)
    self.store.path.unlink()
    target = self.directory / "elsewhere.json"
    target.write_text(json.dumps({"schema_version": 1, "auto_start": True, "revision": 1, "updated_at": "test"}))
    self.store.path.symlink_to(target)
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      apply_startup_policy(self.config)
    self.assertEqual(self.config["initial_state"], "stopped")

  def test_live_enabling_requires_a_loaded_account_and_disabling_remains_available_after_failure(self):
    self.live()
    self.assertFalse(self.client.get("/api/v1/startup-settings").json()["can_enable"])
    self.assertEqual(self.save().status_code, 409)
    self.ready_profile()
    self.assertEqual(self.save().status_code, 200)
    (self.directory / ".nfi-live-status.json").write_text(json.dumps({"phase": "error", "revision": 1}))
    self.assertFalse(self.client.get("/api/v1/startup-settings").json()["can_enable"])
    self.assertEqual(self.save(False, 1).status_code, 200)

  def test_live_only_autostarts_a_configured_worker_on_container_boot_never_on_reload(self):
    self.live()
    self.ready_profile()
    self.store.save(True, 0)
    for allowed, reconfig, expected in (("0", False, "stopped"), ("1", True, "stopped"), ("1", False, "running")):
      with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live", "NFI_STARTUP_AUTOSTART_ALLOWED": allowed}):
        apply_startup_policy(self.config, reconfig)
      self.assertEqual(self.config["initial_state"], expected)
    (self.directory / "live-profile.json").unlink()
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live", "NFI_STARTUP_AUTOSTART_ALLOWED": "1"}):
      apply_startup_policy(self.config)
    self.assertEqual(self.config["initial_state"], "stopped")

  def test_separate_directories_keep_paper_and_live_preferences_independent(self):
    self.assertEqual(self.save().status_code, 200)
    other = StartupStore(self.directory / "another-bot")
    self.assertFalse(other.read()["auto_start"])

  def test_unmanaged_bots_and_research_services_do_not_get_startup_overrides(self):
    self.config["initial_state"] = "running"
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": ""}):
      apply_startup_policy(self.config)
    self.assertEqual(self.config["initial_state"], "running")
    _, _, client = self.make_app("")
    self.assertEqual(client.get("/api/v1/startup-settings").status_code, 404)
