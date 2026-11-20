import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import test_live_web
from freqtrade.configuration import Configuration
from freqtrade.configuration.config_validation import validate_config_consistency
from freqtrade.enums import RunMode
from freqtrade.resolvers import StrategyResolver
from nfi_account.origin import normalized_origin
from nfi_live.deployment import create_deployment, validate_deployment
from nfi_live.research_worker import build_research_config
from nfi_live.storage import LiveStore, read_json
from nfi_live.trading import LEVERAGE_KEYS, apply_trading_settings, public_research_snapshot


class MultipleBotWebTests(unittest.TestCase):
  setUp = test_live_web.LiveWebTests.setUp
  setup_account = test_live_web.LiveWebTests.setup_account
  save = test_live_web.LiveWebTests.save

  def futures(self, **changes):
    self.exchange.private_get_account_config.return_value["data"][0]["acctLv"] = "2"
    return self.save(trading_mode="futures", confirm_futures=True, leverage=1.5, **changes)

  def test_futures_profile_and_real_strategy_validate_offline_with_uniform_leverage(self):
    self.setup_account()
    response = self.futures()
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual([call[0] for call in self.exchange.mock_calls], ["private_get_account_config", "fetch_balance"])
    self.assertEqual(self.factory.call_args.args[0]["options"]["defaultType"], "swap")
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"}):
      config = Configuration(
        {
          "config": [str(self.store.profile_path)],
          "user_data_dir": str(self.directory),
          "strategy_path": str(self.directory / "strategies"),
        },
        RunMode.LIVE,
      ).get_config()
      strategy = StrategyResolver.load_strategy(config)
      validate_config_consistency(config)
    self.assertTrue(strategy.can_short)
    self.assertTrue(strategy.is_futures_mode)
    self.assertEqual(config["margin_mode"], "isolated")
    for key in ("ccxt_config", "ccxt_async_config"):
      self.assertTrue(config["exchange"][key]["enableRateLimit"])
      self.assertGreaterEqual(config["exchange"][key]["rateLimit"], 200)
    for key in LEVERAGE_KEYS:
      self.assertEqual(getattr(strategy, key), 1.5)
    self.assertEqual(config["initial_state"], "stopped")
    self.assertNotIn("available_capital", response.json())

  def test_okx_futures_transport_preserves_slower_limits_and_spot_transport(self):
    from copy import deepcopy

    config = {"exchange": {"name": "okx", "ccxt_config": {"rateLimit": 500}, "ccxt_async_config": {"rateLimit": 60}}}
    spot = deepcopy(config)
    apply_trading_settings(spot, "spot")
    self.assertEqual(spot["exchange"]["ccxt_config"]["rateLimit"], 500)
    self.assertEqual(spot["exchange"]["ccxt_async_config"]["rateLimit"], 60)
    apply_trading_settings(config, "futures")
    self.assertEqual(config["exchange"]["ccxt_config"]["rateLimit"], 500)
    self.assertEqual(config["exchange"]["ccxt_async_config"]["rateLimit"], 200)

  def test_futures_requires_confirmation_and_an_enabled_okx_account(self):
    self.setup_account()
    response = self.save(trading_mode="futures")
    self.assertEqual(response.json()["detail"], "live_futures_confirmation_required")
    self.factory.assert_not_called()
    response = self.save(trading_mode="futures", confirm_futures=True)
    self.assertEqual(response.json()["detail"], "live_futures_account_required")
    self.assertFalse(self.store.profile_path.exists())
    self.exchange.fetch_balance.assert_not_called()

  def test_both_okx_futures_volume_filters_initialize_without_ticker_quote_volume(self):
    from freqtrade.enums import CandleType
    from freqtrade.plugins.pairlist.VolumePairList import VolumePairList
    from freqtrade.exceptions import OperationalException

    self.setup_account()
    self.assertEqual(self.futures().status_code, 200)
    config = self.store.profile()
    config["candle_type_def"] = CandleType.FUTURES
    exchange = MagicMock()
    exchange.get_option.return_value = False
    exchange.ohlcv_candle_limit.return_value = 100
    filters = [
      (index, value) for index, value in enumerate(config["pairlists"]) if value["method"] == "VolumePairList"
    ]
    self.assertEqual(len(filters), 2)
    for index, value in filters:
      plugin = VolumePairList(exchange, MagicMock(), config, value, index)
      self.assertFalse(plugin.needstickers)
      self.assertEqual(plugin._lookback_period, 24)
      self.assertEqual(plugin._lookback_timeframe, "1h")
      self.assertGreaterEqual(value["refresh_period"], 3600)
      broken = {key: field for key, field in value.items() if key not in ("lookback_timeframe", "lookback_period")}
      with self.assertRaises(OperationalException):
        VolumePairList(exchange, MagicMock(), config, broken, index)

  def test_failed_futures_worker_management_reports_saved_futures_mode(self):
    self.setup_account()
    self.assertEqual(self.futures().status_code, 200)
    self.store.write_status("error", 1, "live_start_failed")
    self.config.update(strategy=None, runmode=RunMode.WEBSERVER)
    with patch("nfi_live.get_rpc_optional", return_value=None):
      result = self.client.get("/api/v1/show_config").json()
    self.assertTrue(result["nfi_live_configured"])
    self.assertEqual(result["runmode"], "webserver")
    self.assertEqual(result["trading_mode"], "futures")
    self.assertEqual(result["margin_mode"], "isolated")

  def test_deployed_mode_and_trading_history_prevent_mode_changes_without_mutation(self):
    self.setup_account()
    with patch.dict(os.environ, {"NFI_TRADING_MODE": "futures"}):
      info = self.client.get("/api/v1/live-settings").json()
      self.assertEqual(info["trading_mode"], "futures")
      self.assertTrue(info["mode_locked"])
      self.assertEqual(self.save(trading_mode="spot").json()["detail"], "live_instance_mode_locked")
      self.assertEqual(self.futures().status_code, 200)
    before = self.store.profile_path.read_bytes()
    with patch.object(LiveStore, "database_counts", return_value={"trades": 1, "open_trades": 0, "open_orders": 0}):
      response = self.save(revision=1, trading_mode="spot")
      self.assertEqual(response.json()["detail"], "live_mode_has_history")
    self.assertEqual(self.store.profile_path.read_bytes(), before)

  def test_open_positions_block_leverage_changes_and_recipe_preserves_leverage(self):
    from nfi_live.recipe import current_document, update_profile

    self.setup_account()
    self.assertEqual(self.futures().status_code, 200)
    before = self.store.profile_path.read_bytes()
    self.factory.reset_mock()
    with patch.object(LiveStore, "database_counts", return_value={"trades": 1, "open_trades": 1, "open_orders": 0}):
      response = self.save(revision=1, trading_mode="futures", confirm_futures=True, leverage=2)
      self.assertEqual(response.json()["detail"], "live_trading_has_positions")
    self.factory.assert_not_called()
    self.assertEqual(self.store.profile_path.read_bytes(), before)
    profile = self.store.profile()
    updated = update_profile(profile, current_document(profile))
    for key in LEVERAGE_KEYS:
      self.assertEqual(updated["nfi_parameters"][key], 1.5)

  def test_public_snapshot_contains_applied_recipe_and_leverage_without_secrets(self):
    self.setup_account()
    self.assertEqual(self.futures().status_code, 200)
    snapshot = read_json(self.directory / "research-public/snapshot.json")
    self.assertEqual(snapshot["config"]["nfi_live_leverage"], 1.5)
    self.assertEqual(snapshot["config"]["dry_run_wallet"], 1000)
    self.assertEqual(snapshot["recipe"]["revision"], 7)
    for secret in ("fixture-key", "fixture-secret", "fixture-passphrase", self.password):
      self.assertNotIn(secret, json.dumps(snapshot))
    self.assertNotIn("exchange", snapshot["config"])
    profile = self.store.profile()
    profile["nfi_parameters"]["proxy_password"] = "private-transport-token"
    self.assertNotIn("private-transport-token", json.dumps(public_research_snapshot(profile, snapshot["recipe"])))

  def test_only_explicit_console_origins_can_configure_and_never_bootstrap_admin(self):
    self.app.state.nfi_console_origins = (normalized_origin("https://console.example.test"),)
    headers = {"Origin": "https://console.example.test", "Sec-Fetch-Site": "cross-site"}
    response = self.client.post(
      "/api/v1/live/setup", json={"username": "live-admin", "password": self.password}, headers=headers
    )
    self.assertEqual(response.status_code, 403)
    self.setup_account()
    self.assertEqual(self.client.put("/api/v1/live-settings", json=self.body, headers=headers).status_code, 200)
    headers["Origin"] = "https://other.example.test"
    before = self.store.profile_path.read_bytes()
    self.assertEqual(
      self.client.put("/api/v1/live-settings", json={**self.body, "revision": 1}, headers=headers).status_code, 403
    )
    self.assertEqual(self.store.profile_path.read_bytes(), before)

  def test_unused_legacy_instance_can_return_to_spot_without_swap_market_options(self):
    config = apply_trading_settings({}, "futures", 2)
    apply_trading_settings(config, "spot")
    self.assertEqual(config["exchange"]["ccxt_async_config"]["options"]["fetchMarkets"]["types"], ["spot"])
    self.assertFalse(any(key in config["nfi_parameters"] for key in LEVERAGE_KEYS))


class DeploymentTests(unittest.TestCase):
  def test_instances_have_independent_private_data_and_research_has_no_account_mount(self):
    with tempfile.TemporaryDirectory() as name:
      root = Path(name)
      (root / "NostalgiaForInfinityX8.py").write_text("# strategy snapshot\n")
      for instance, mode, port in (("spot-one", "spot", 18182), ("futures-two", "futures", 18183)):
        result = create_deployment(root, instance, mode, port, ["https://console.example.test"])
        directory = Path(result["directory"])
        compose = read_json(result["compose"])
        bot, research = (compose["services"][key] for key in ("bot", "research"))
        self.assertEqual(bot["environment"]["FREQTRADE__INITIAL_STATE"], "stopped")
        self.assertEqual(bot["environment"]["NFI_TRADING_MODE"], mode)
        self.assertEqual(bot["ports"], [f"127.0.0.1:{port}:8080"])
        self.assertEqual((directory / "research-auth.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertNotIn("ports", research)
        for volume in research["volumes"]:
          self.assertNotIn(f"{directory}/live:/", volume)
          self.assertNotIn("docker.sock", volume)
        self.assertTrue((directory / "live/strategies/NostalgiaForInfinityX8.py").exists())
        with self.assertRaises(FileExistsError):
          create_deployment(root, instance, mode, port, [])
      directories = root / "user_data/bots"
      self.assertNotEqual(
        read_json(directories / "spot-one/research-auth.json"),
        read_json(directories / "futures-two/research-auth.json"),
      )
      self.assertFalse((directories / "spot-one/live/live-profile.json").exists())

  def test_invalid_deployments_are_rejected(self):
    for name, mode, port, origins in (
      ("../escape", "spot", 18082, []),
      ("ok", "cross", 18082, []),
      ("ok", "spot", 8080.5, []),
      ("ok", "futures", 80, []),
      ("ok", "spot", 18082, ["*"]),
      ("ok", "spot", 18082, ["https://user:secret@example.test"]),
      ("ok", "spot", 18082, ["https://example.test/path"]),
      ("ok", "spot", 18082, ["https://example.test:0"]),
    ):
      with self.subTest(name=name, mode=mode, origins=origins), self.assertRaises(ValueError):
        validate_deployment(name, mode, port, origins, "nfi-paper:multi")

  def test_research_worker_uses_swap_pairs_no_credentials_and_uniform_leverage(self):
    with tempfile.TemporaryDirectory() as name:
      root = Path(name)
      (root / "configs").mkdir()
      for filename in ("research.json", "blacklist-okx.json"):
        (root / "configs" / filename).write_bytes((Path("/live-configs") / filename).read_bytes())
      config = build_research_config(root, root / "data", {"username": "internal", "password": "private"}, "futures")
      self.assertEqual(config["exchange"]["key"], "")
      self.assertEqual(config["exchange"]["secret"], "")
      self.assertTrue(all(pair.endswith("/USDT:USDT") for pair in config["exchange"]["pair_whitelist"]))
      self.assertEqual(config["nfi_live_leverage"], 1)
      self.assertEqual(config["margin_mode"], "isolated")
      self.assertNotIn("add_config_files", config)


if __name__ == "__main__":
  unittest.main()
