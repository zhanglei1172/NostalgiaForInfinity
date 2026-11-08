import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import test_live_web
from freqtrade.enums import State
from nfi_live.storage import LiveStore, atomic_json


class LiveRecipeTests(unittest.TestCase):
  setUp = test_live_web.LiveWebTests.setUp
  setup_account = test_live_web.LiveWebTests.setup_account
  save = test_live_web.LiveWebTests.save

  def ready(self):
    self.setup_account()
    self.assertEqual(self.save().status_code, 200)
    self.sync_config()
    self.store.write_status("ready", 1)
    self.rpc = SimpleNamespace(_freqtrade=SimpleNamespace(state=State.STOPPED, _measure_execution=object()))
    patch("nfi_live.recipe.get_rpc_optional", return_value=self.rpc).start()

  def sync_config(self):
    profile = deepcopy(self.store.profile())
    profile.pop("api_server")
    self.config.update(profile, runmode="live")

  def info(self):
    response = self.client.get("/api/v1/live-recipe")
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()

  def draft(self, **changes):
    info = self.info()
    return self.client.put(
      "/api/v1/live-recipe",
      json={"revision": info["saved"]["revision"], "settings": {**info["saved"]["settings"], **changes}},
    )

  def apply(self, rollback=False, **changes):
    info = self.info()
    return self.client.post(
      "/api/v1/live-recipe/" + ("rollback" if rollback else "apply"),
      json={
        "revision": info["saved"]["revision"],
        "live_revision": info["live_revision"],
        "current_password": self.password,
        "confirm_live": True,
        **changes,
      },
    )

  def test_unconfigured_account_can_compare_and_save_a_private_draft_without_exchange_access(self):
    self.assertEqual(self.client.get("/api/v1/live-recipe").status_code, 401)
    self.setup_account()
    source = (self.source / "recipes/active.json").read_bytes()
    info = self.info()
    self.assertFalse(info["configured"])
    self.assertEqual(info["apply_blocker"], "live_recipe_account_required")
    self.assertIsNone(info["applied_settings"])
    self.assertEqual(info["paper_applied"]["revision"], 7)
    self.assertEqual(self.draft(max_open_trades=8).status_code, 200)
    self.assertEqual(self.info()["saved"]["settings"]["max_open_trades"], 8)
    self.assertEqual((self.directory / ".nfi-live-recipe.json").stat().st_mode & 0o777, 0o600)
    self.assertEqual((self.source / "recipes/active.json").read_bytes(), source)
    self.assertFalse(self.store.profile_path.exists())
    self.assertFalse((self.directory / "trades-live.sqlite").exists())
    self.assertEqual(self.apply().status_code, 409)
    self.factory.assert_not_called()

  def test_first_account_configuration_uses_an_explicitly_saved_live_draft(self):
    self.setup_account()
    self.assertEqual(self.draft(max_open_trades=8, max_slippage=0.01).status_code, 200)
    self.assertEqual(self.save().status_code, 200)
    profile = self.store.profile()
    self.assertEqual(profile["max_open_trades"], 8)
    self.assertEqual(profile["nfi_parameters"]["max_slippage"], 0.01)
    self.assertEqual(profile["nfi_live_recipe_revision"], 1)
    self.assertEqual(profile["initial_state"], "stopped")

  def test_saving_a_draft_changes_neither_live_runtime_nor_paper_and_stale_saves_fail(self):
    self.ready()
    before = self.store.profile_path.read_bytes()
    source = (self.source / "recipes/active.json").read_bytes()
    info = self.info()
    self.assertEqual(self.draft(max_open_trades=8).status_code, 200)
    stale = self.client.put("/api/v1/live-recipe", json={"revision": 0, "settings": info["saved"]["settings"]})
    self.assertEqual(stale.status_code, 409)
    self.assertEqual(self.store.profile_path.read_bytes(), before)
    self.assertEqual((self.source / "recipes/active.json").read_bytes(), source)

  def test_apply_preserves_keys_budget_strategy_database_and_startup_preference_and_stays_stopped(self):
    self.ready()
    before = self.store.profile()
    strategy = (self.directory / "strategies/NostalgiaForInfinityX8.py").read_bytes()
    atomic_json(self.directory / ".nfi-startup.json", {"auto_start": True, "revision": 1})
    startup = (self.directory / ".nfi-startup.json").read_bytes()
    self.assertEqual(self.draft(max_open_trades=8, max_slippage=0.01).status_code, 200)
    self.factory.reset_mock()
    response = self.apply()
    self.assertEqual(response.status_code, 200, response.text)
    after = self.store.profile()
    self.assertEqual(after["max_open_trades"], 8)
    self.assertEqual(after["nfi_parameters"]["max_slippage"], 0.01)
    self.assertEqual(after["nfi_live_revision"], 2)
    self.assertEqual(after["nfi_live_recipe_revision"], 1)
    self.assertEqual(after["initial_state"], "stopped")
    for key in ("available_capital", "exchange", "api_server", "nfi_live_account"):
      self.assertEqual(after[key], before[key])
    for key in ("fee", "tradable_balance_ratio", "dry_run_wallet", "original_config"):
      self.assertNotIn(key, after)
    self.assertEqual((self.directory / "strategies/NostalgiaForInfinityX8.py").read_bytes(), strategy)
    self.assertEqual((self.directory / ".nfi-startup.json").read_bytes(), startup)
    self.assertFalse((self.directory / "trades-live.sqlite").exists())
    self.assertEqual(self.store.status()["phase"], "applying")
    self.assertFalse(self.info()["can_apply"])
    self.assertEqual(self.apply().status_code, 409)
    self.factory.assert_not_called()
    text = response.text + self.client.get("/api/v1/live-recipe").text
    for secret in ("fixture-key", "fixture-secret", "fixture-passphrase", self.password):
      self.assertNotIn(secret, text)

  def test_rollback_restores_only_the_previous_recipe_as_a_new_revision(self):
    self.ready()
    original = self.store.profile()
    self.assertEqual(self.draft(max_open_trades=8).status_code, 200)
    self.assertEqual(self.apply().status_code, 200)
    self.sync_config()
    self.store.write_status("ready", 2)
    self.assertTrue(self.info()["can_rollback"])
    response = self.apply(rollback=True)
    self.assertEqual(response.status_code, 200, response.text)
    restored = self.store.profile()
    self.assertEqual(restored["max_open_trades"], original["max_open_trades"])
    self.assertEqual(restored["nfi_live_revision"], 3)
    self.assertEqual(restored["nfi_live_recipe_revision"], 2)
    self.assertEqual(restored["available_capital"], original["available_capital"])
    self.assertEqual(restored["exchange"], original["exchange"])
    self.assertEqual(restored["initial_state"], "stopped")
    backup = (self.directory / ".nfi-live-recipe-previous.json").read_text()
    self.assertNotIn("fixture-secret", backup)
    self.assertNotIn("available_capital", backup)

  def test_failed_worker_can_recover_by_rolling_back_from_management_mode(self):
    self.ready()
    self.draft(max_open_trades=8)
    self.assertEqual(self.apply().status_code, 200)
    self.store.write_status("error", 2, "live_start_failed")
    with patch("nfi_live.recipe.get_rpc_optional", return_value=None):
      self.assertFalse(self.info()["can_apply"])
      self.assertTrue(self.info()["can_rollback"])
      self.assertEqual(self.apply(rollback=True).status_code, 200)
    self.assertEqual(self.store.profile()["max_open_trades"], 6)
    self.assertEqual(self.store.profile()["initial_state"], "stopped")

  def test_running_or_paused_bots_cannot_apply_or_rollback(self):
    self.ready()
    self.draft(max_open_trades=8)
    before = self.store.profile_path.read_bytes()
    for state in (State.RUNNING, State.PAUSED):
      self.rpc._freqtrade.state = state
      self.assertEqual(self.apply().json()["detail"], "live_stop_required")
      self.assertEqual(self.apply(rollback=True).status_code, 409)
    self.assertEqual(self.store.profile_path.read_bytes(), before)

  def test_open_positions_or_orders_block_both_apply_and_rollback(self):
    self.ready()
    self.draft(max_open_trades=8)
    for opened, orders in ((1, 0), (0, 1)):
      with patch.object(
        LiveStore, "database_counts", return_value={"trades": 2, "open_trades": opened, "open_orders": orders}
      ):
        self.assertEqual(self.apply().json()["detail"], "live_recipe_has_positions")
        self.assertEqual(self.apply(rollback=True).status_code, 409)
    self.assertEqual(self.store.profile()["nfi_live_revision"], 1)

  def test_confirmation_password_origin_and_both_revisions_are_required(self):
    self.ready()
    self.draft(max_open_trades=8)
    before = self.store.profile_path.read_bytes()
    for changes, status in (
      ({"confirm_live": False}, 400),
      ({"current_password": "wrong"}, 400),
      ({"revision": 0}, 409),
      ({"live_revision": 0}, 409),
    ):
      response = self.apply(**changes)
      self.assertEqual(response.status_code, status, response.text)
      self.assertNotIn("wrong", response.text)
    response = self.client.put(
      "/api/v1/live-recipe",
      json={"revision": 1, "settings": self.info()["saved"]["settings"]},
      headers={"Origin": "https://evil.test"},
    )
    self.assertEqual(response.status_code, 403)
    self.assertEqual(self.store.profile_path.read_bytes(), before)

  def test_invalid_fields_do_not_change_the_draft(self):
    self.ready()
    self.assertEqual(self.draft(max_open_trades=100).status_code, 400)
    self.assertEqual(self.draft(research_pairs=["BTC/USDT", "BTC/USDT", "ETH/USDT"]).status_code, 400)
    self.assertFalse((self.directory / ".nfi-live-recipe.json").exists())

  def test_strategy_fingerprints_show_research_drift_without_replacing_live_code(self):
    self.ready()
    self.assertTrue(self.info()["strategy"]["matches"])
    with (self.source / "NostalgiaForInfinityX8.py").open("a") as stream:
      stream.write("\n# different research copy\n")
    self.assertFalse(self.info()["strategy"]["matches"])
    self.draft(max_open_trades=8)
    self.assertEqual(self.apply().status_code, 200)
    self.assertFalse(self.info()["strategy"]["matches"])

  def test_runtime_comparison_does_not_claim_a_pending_profile_is_already_loaded(self):
    self.ready()
    self.draft(max_open_trades=8)
    self.assertEqual(self.apply().status_code, 200)
    info = self.info()
    self.assertEqual(info["applied_settings"]["max_open_trades"], 8)
    self.assertEqual(info["runtime_settings"]["max_open_trades"], 6)
    self.assertEqual(info["runtime_live_revision"], 1)
    self.assertEqual(info["live_revision"], 2)
    self.sync_config()
    self.store.write_status("ready", 2)
    self.assertEqual(self.info()["runtime_settings"]["max_open_trades"], 8)

  def test_applied_profile_passes_freqtrade_configuration_validation_offline(self):
    from freqtrade.configuration import Configuration
    from freqtrade.configuration.config_validation import validate_config_consistency
    from freqtrade.enums import RunMode
    from freqtrade.resolvers import StrategyResolver

    self.ready()
    self.draft(max_open_trades=8)
    self.assertEqual(self.apply().status_code, 200)
    with patch.dict("os.environ", {"NFI_RECIPE_ROLE": "live"}):
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
    self.assertEqual(config["max_open_trades"], 8)
    self.assertEqual(config["initial_state"], "stopped")


if __name__ == "__main__":
  unittest.main()
