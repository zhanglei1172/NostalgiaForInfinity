import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.enums import State
from freqtrade.rpc.api_server.deps import get_api_config, get_rpc
from nfi_account import configure_account_api
from nfi_live import configure_live_api
from nfi_live.__main__ import child_command, child_environment, redactions
from nfi_live.storage import LiveStore, atomic_json
from nfi_research.recipe import exchange_defaults


class LiveWebTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name) / "live"
    self.source = Path(self.temporary.name) / "source"
    (self.source / "configs").mkdir(parents=True)
    for name in ("exampleconfig.json", "blacklist-okx.json"):
      (self.source / "configs" / name).write_bytes((Path("/live-configs") / name).read_bytes())
    (self.source / "NostalgiaForInfinityX8.py").write_bytes(Path("/live-strategy.py").read_bytes())
    (self.source / "recipes").mkdir()
    atomic_json(
      self.source / "recipes/active.json",
      {"schema_version": 1, "revision": 7, "settings": exchange_defaults({"exchange": {"name": "okx"}})},
    )
    self.store = LiveStore(self.directory, self.source)
    self.config = self.store.ensure_bootstrap()
    self.config.update(user_data_dir=self.directory, runmode="webserver")
    self.app = FastAPI()
    self.app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    self.manager = configure_account_api(self.app, self.config)
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live", "NFI_LIVE_SOURCE": str(self.source)}):
      configure_live_api(self.app, self.config)
    self.client = TestClient(self.app, base_url="http://127.0.0.1:8080")
    self.password = "fixture-web-password"
    self.body = {
      "revision": 0,
      "account_label": "专用实盘",
      "available_capital": 1000,
      "current_password": self.password,
      "api_key": "fixture-key",
      "api_secret": "fixture-secret",
      "passphrase": "fixture-passphrase",
    }
    self.exchange = MagicMock()
    self.exchange.private_get_account_config.return_value = {"data": [{"uid": "123456789"}]}
    self.exchange.fetch_balance.return_value = {"USDT": {"free": 10000, "used": 50, "total": 10050}}
    self.factory = patch("nfi_live.ccxt.okx", return_value=self.exchange).start()
    self.addCleanup(patch.stopall)

  def setup_account(self):
    response = self.client.post("/api/v1/live/setup", json={"username": "live-admin", "password": self.password})
    self.assertEqual(response.status_code, 200)
    self.client.auth = ("live-admin", self.password)

  def test_fresh_management_configuration_passes_real_freqtrade_validation_offline(self):
    from copy import deepcopy

    from freqtrade.configuration.config_validation import validate_config_consistency
    from freqtrade.enums import RunMode

    config = deepcopy(self.config)
    config["runmode"] = RunMode.WEBSERVER
    validate_config_consistency(config)
    self.assertTrue(config["dry_run"])
    self.assertEqual(config["initial_state"], "stopped")
    self.assertFalse(self.store.profile_path.exists())

  def save(self, **changes):
    return self.client.put("/api/v1/live-settings", json={**self.body, **changes})

  def test_first_admin_is_created_on_web_without_a_default_password_and_cannot_be_reset_anonymously(self):
    self.assertTrue(self.client.get("/api/v1/live/setup-status").json()["required"])
    self.assertEqual(self.client.get("/api/v1/live-settings").status_code, 401)
    self.setup_account()
    self.assertFalse(self.client.get("/api/v1/live/setup-status").json()["required"])
    account = (self.directory / ".nfi-account.json").read_text()
    self.assertNotIn(self.password, account)
    self.assertEqual((self.directory / ".nfi-account.json").stat().st_mode & 0o777, 0o600)
    duplicate = self.client.post("/api/v1/live/setup", json={"username": "attacker", "password": self.password})
    self.assertEqual(duplicate.status_code, 409)
    self.assertEqual((self.directory / ".nfi-account.json").read_text(), account)

  def test_invalid_setup_requests_freeze_creation_until_the_deadline(self):
    clock = [1000000.0]
    self.manager.attempts.now = lambda: clock[0]
    for _ in range(4):
      response = self.client.post("/api/v1/live/setup", json={"username": "!", "password": self.password})
      self.assertEqual(response.status_code, 400)
    response = self.client.post("/api/v1/live/setup", json={"username": "!", "password": self.password})
    self.assertEqual(response.status_code, 429)
    self.assertEqual(response.headers["Retry-After"], "300")
    clock[0] += 20
    response = self.client.post("/api/v1/live/setup", json={"username": "live-admin", "password": self.password})
    self.assertEqual(response.status_code, 429)
    self.assertEqual(response.json()["retry_after"], 280)
    self.assertFalse(self.manager.path.exists())
    self.factory.assert_not_called()
    clock[0] += 280
    self.setup_account()

  def test_live_settings_and_reload_share_the_password_freeze_and_jwt_reads_continue(self):
    from freqtrade.rpc.api_server.api_auth import create_token

    self.setup_account()
    token = create_token({"identity": {"u": "live-admin"}}, self.manager.generation)
    self.client.auth = None
    self.client.headers["Authorization"] = "Bearer " + token
    for _ in range(4):
      self.assertEqual(self.save(current_password="wrong").status_code, 400)
    response = self.client.post("/api/v1/live-settings/reload", json={"current_password": "wrong"})
    self.assertEqual(response.status_code, 429)
    response = self.save()
    self.assertEqual(response.status_code, 429)
    self.assertIn("Retry-After", response.headers)
    self.assertEqual(self.client.get("/api/v1/live-settings").status_code, 200)
    self.assertFalse(self.store.profile_path.exists())
    self.factory.assert_not_called()

  def test_cross_site_and_nonlocal_bootstrap_requests_are_rejected(self):
    data = {"username": "live-admin", "password": self.password}
    self.assertEqual(
      self.client.post("/api/v1/live/setup", json=data, headers={"Origin": "https://evil.test"}).status_code, 403
    )
    self.assertEqual(self.client.post("http://example.test/api/v1/live/setup", json=data).status_code, 403)
    self.assertFalse((self.directory / ".nfi-account.json").exists())

  def test_validation_and_auth_errors_never_echo_submitted_secrets(self):
    self.setup_account()
    for body in ({**self.body, "available_capital": "fixture-secret"}, {**self.body, "unknown": "fixture-secret"}):
      response = self.client.put("/api/v1/live-settings", json=body)
      self.assertEqual(response.status_code, 400)
      for secret in ("fixture-secret", "fixture-key", self.password):
        self.assertNotIn(secret, response.text)
    response = self.save(current_password="wrong-password")
    self.assertEqual(response.status_code, 400)
    self.factory.assert_not_called()
    self.assertFalse(self.store.profile_path.exists())

  def test_reverse_proxy_same_origin_can_check_and_save_but_cross_site_cannot(self):
    self.setup_account()
    headers = {"Origin": "https://console.example.test", "Sec-Fetch-Site": "same-origin"}
    check = self.client.post(
      "/api/v1/live-settings/check",
      json={key: self.body[key] for key in ("api_key", "api_secret", "passphrase")},
      headers=headers,
    )
    self.assertEqual(check.status_code, 200, check.text)
    rejected = self.client.put(
      "/api/v1/live-settings", json=self.body, headers={**headers, "Sec-Fetch-Site": "cross-site"}
    )
    self.assertEqual(rejected.status_code, 403)
    self.assertFalse(self.store.profile_path.exists())
    saved = self.client.put("/api/v1/live-settings", json=self.body, headers=headers)
    self.assertEqual(saved.status_code, 200, saved.text)
    self.assertEqual(saved.json()["state"], "stopped")
    self.assertEqual(self.manager.attempts.remaining(), 0)

  def test_proxy_metadata_cannot_bypass_local_only_first_admin_setup(self):
    response = self.client.post(
      "/api/v1/live/setup",
      json={"username": "live-admin", "password": self.password},
      headers={"Origin": "https://console.example.test", "Sec-Fetch-Site": "same-origin"},
    )
    self.assertEqual(response.status_code, 403)
    self.assertFalse(self.manager.path.exists())

  def test_save_reads_identity_and_balance_only_persists_privately_and_never_starts_trading(self):
    self.setup_account()
    response = self.save()
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual([call[0] for call in self.exchange.mock_calls], ["private_get_account_config", "fetch_balance"])
    saved = self.store.profile()
    self.assertFalse(saved["dry_run"])
    self.assertEqual(saved["initial_state"], "stopped")
    self.assertEqual(saved["nfi_recipe_revision"], 7)
    self.assertEqual(saved["nfi_live_revision"], 1)
    self.assertEqual(saved["exchange"]["password"], "fixture-passphrase")
    self.assertEqual(self.store.profile_path.stat().st_mode & 0o777, 0o600)
    self.assertEqual(
      (self.directory / "strategies/NostalgiaForInfinityX8.py").read_bytes(), Path("/live-strategy.py").read_bytes()
    )
    info = self.client.get("/api/v1/live-settings")
    self.assertTrue(info.json()["credentials_configured"])
    self.assertEqual(info.json()["account_uid"], "123456789")
    for secret in ("fixture-key", "fixture-secret", "fixture-passphrase", self.password):
      self.assertNotIn(secret, response.text + info.text)
      self.assertNotIn(secret, saved["api_server"]["password"])
    self.assertEqual(info.json()["phase"], "applying")

  def test_web_generated_live_profile_passes_real_freqtrade_validation_offline(self):
    from freqtrade.configuration import Configuration
    from freqtrade.configuration.config_validation import validate_config_consistency
    from freqtrade.enums import RunMode
    from freqtrade.resolvers import StrategyResolver

    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"}):
      config = Configuration(
        {
          "config": [str(self.store.profile_path)],
          "user_data_dir": str(self.directory),
          "strategy_path": str(self.directory / "strategies"),
        },
        RunMode.LIVE,
      ).get_config()
      StrategyResolver.load_strategy(config)
      validate_config_consistency(config)
    self.assertFalse(config["dry_run"])
    self.assertEqual(config["initial_state"], "stopped")

  def test_legacy_web_account_migration_preserves_the_original_files_and_password(self):
    from nfi_account.credentials import AccountManager

    legacy_config = {"dry_run": False, "exchange": {"name": "okx"}, "api_server": {}}
    legacy_credentials = {
      "exchange": {"key": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"},
      "api_server": {"username": "legacy-admin", "password": self.password, "jwt_secret_key": "a" * 64},
    }
    atomic_json(self.directory / "config.json", legacy_config)
    atomic_json(self.directory / "credentials.json", legacy_credentials)
    paths = [self.directory / name for name in ("config.json", "credentials.json")]
    originals = [path.read_bytes() for path in paths]
    self.store.migrate_legacy()
    profile = self.store.profile()
    self.assertEqual(profile["nfi_live_revision"], 1)
    self.assertEqual(profile["initial_state"], "stopped")
    self.assertEqual(profile["exchange"]["secret"], "fixture-secret")
    self.assertNotIn(self.password, (self.directory / ".nfi-account.json").read_text())
    manager = AccountManager({"api_server": profile["api_server"], "user_data_dir": self.directory})
    self.assertTrue(manager.verify("legacy-admin", self.password))
    self.assertEqual([path.read_bytes() for path in paths], originals)

  def test_empty_secret_inputs_preserve_saved_values_and_stale_saves_do_not_overwrite(self):
    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    response = self.save(revision=1, api_key="", api_secret="", passphrase="", available_capital=900)
    self.assertEqual(response.status_code, 200)
    self.assertEqual(self.store.profile()["exchange"]["key"], "fixture-key")
    self.assertEqual(self.store.profile()["available_capital"], 900)
    self.assertEqual(self.save(revision=1).status_code, 409)
    self.assertEqual(self.store.profile()["nfi_live_revision"], 2)

  def test_running_bots_and_budget_changes_with_open_positions_are_blocked(self):
    self.setup_account()
    rpc = SimpleNamespace(_freqtrade=SimpleNamespace(state=State.RUNNING))
    with patch("nfi_live.get_rpc_optional", return_value=rpc):
      self.assertEqual(self.save().status_code, 409)
    self.factory.assert_not_called()
    self.assertEqual(self.save().status_code, 200)
    with patch.object(LiveStore, "database_counts", return_value={"trades": 2, "open_trades": 1, "open_orders": 0}):
      response = self.save(revision=1, available_capital=500)
    self.assertEqual(response.status_code, 409)
    self.assertEqual(self.store.profile()["available_capital"], 1000)

  def test_an_account_with_trading_history_cannot_be_replaced_by_another_okx_uid(self):
    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    self.exchange.private_get_account_config.return_value = {"data": [{"uid": "999999999"}]}
    with patch.object(LiveStore, "database_counts", return_value={"trades": 2, "open_trades": 0, "open_orders": 0}):
      self.assertEqual(self.save(revision=1).status_code, 409)
    self.assertEqual(self.store.profile()["nfi_live_account"]["uid"], "123456789")

  def test_failed_connection_or_insufficient_balance_does_not_write_a_profile(self):
    self.setup_account()
    self.exchange.fetch_balance.return_value = {"USDT": {"free": 50}}
    self.assertEqual(self.save().status_code, 400)
    self.assertFalse(self.store.profile_path.exists())
    import ccxt

    self.exchange.fetch_balance.side_effect = ccxt.AuthenticationError("fixture-secret must not be returned")
    response = self.save()
    self.assertEqual(response.status_code, 400)
    self.assertNotIn("fixture-secret", response.text)
    self.assertFalse(self.store.profile_path.exists())

  def test_invalid_exchange_balances_do_not_bypass_budget_checks(self):
    self.setup_account()
    for value in (float("nan"), float("inf"), -1):
      with self.subTest(value=value):
        self.exchange.fetch_balance.return_value = {"USDT": {"free": value, "used": 0, "total": value}}
        response = self.save()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "live_connection_failed")
        self.assertFalse(self.store.profile_path.exists())

  def test_start_is_blocked_until_the_saved_revision_is_ready_and_explicit_start_still_required(self):
    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    rpc = MagicMock()
    rpc._freqtrade._measure_execution = object()
    rpc._rpc_start.return_value = {"status": "starting trader ..."}
    self.app.dependency_overrides[get_rpc] = lambda: rpc
    self.assertEqual(self.client.post("/api/v1/start").status_code, 409)
    rpc._rpc_start.assert_not_called()
    self.config["nfi_live_revision"] = 1
    self.store.write_status("ready", 1)
    self.assertEqual(self.client.post("/api/v1/start").status_code, 200)
    rpc._rpc_start.assert_called_once()

  def test_worker_commands_and_environment_contain_no_account_credentials_or_budget(self):
    commands = [child_command(self.store, value) for value in (True, False)]
    with patch.dict(
      os.environ,
      {
        "FREQTRADE__EXCHANGE__KEY": "fixture-key",
        "FREQTRADE__AVAILABLE_CAPITAL": "1000",
        "FREQTRADE__API_SERVER__PASSWORD": self.password,
      },
    ):
      env = child_environment(True)
    self.assertNotIn("FREQTRADE__EXCHANGE__KEY", env)
    self.assertNotIn("FREQTRADE__AVAILABLE_CAPITAL", env)
    self.assertNotIn("FREQTRADE__API_SERVER__PASSWORD", env)
    self.assertEqual(env["FREQTRADE__INITIAL_STATE"], "stopped")
    self.assertEqual(env["NFI_STARTUP_AUTOSTART_ALLOWED"], "0")
    self.assertEqual(child_environment(True, allow_startup=True)["NFI_STARTUP_AUTOSTART_ALLOWED"], "1")
    self.assertEqual(child_environment(False, allow_startup=True)["NFI_STARTUP_AUTOSTART_ALLOWED"], "0")
    self.assertNotIn("1000", str(commands))
    self.assertNotIn("fixture-key", str(commands))
    profile = {"exchange": {"key": "fixture-key", "secret": "fixture-secret", "password": "fixture-passphrase"}}
    line = "fixture-key fixture-secret fixture-passphrase"
    for secret in redactions(profile):
      line = line.replace(secret, "[redacted]")
    self.assertNotIn("fixture-", line)

  def test_reload_immediately_blocks_start_even_when_the_saved_revision_does_not_change(self):
    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    self.config["nfi_live_revision"] = 1
    self.store.write_status("ready", 1)
    rpc = MagicMock()
    rpc._freqtrade.state = State.STOPPED
    rpc._freqtrade._measure_execution = object()
    self.app.dependency_overrides[get_rpc] = lambda: rpc
    response = self.client.post("/api/v1/live-settings/reload", json={"current_password": self.password})
    self.assertEqual(response.status_code, 200)
    self.assertEqual(self.store.status()["phase"], "applying")
    self.assertIsNotNone(self.store.reload_nonce())
    self.assertEqual(self.client.post("/api/v1/start").status_code, 409)
    self.assertEqual(self.client.post("/api/v1/pause").status_code, 409)
    rpc._rpc_start.assert_not_called()
    rpc._rpc_pause.assert_not_called()

  def test_database_checks_are_read_only_and_do_not_create_an_empty_database(self):
    self.assertEqual(self.store.database_counts()["trades"], 0)
    path = self.directory / "trades-live.sqlite"
    self.assertFalse(path.exists())
    with closing(sqlite3.connect(path)) as db:
      db.execute("CREATE TABLE trades (is_open INTEGER)")
      db.execute("INSERT INTO trades VALUES (1)")
      db.execute("CREATE TABLE orders (ft_is_open INTEGER)")
      db.execute("INSERT INTO orders VALUES (1)")
      db.commit()
    self.assertEqual(self.store.database_counts(), {"trades": 1, "open_trades": 1, "open_orders": 1})


if __name__ == "__main__":
  unittest.main()
