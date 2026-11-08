import json
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config, get_rpc
from nfi_research.recipe import (
  DEFAULTS,
  RecipeSettings,
  RecipeStore,
  SaveRecipe,
  apply_paper_recipe,
  configure_recipe_api,
  recipe_config,
  exchange_defaults,
)


class RecipeTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.config = {
      "user_data_dir": Path(self.directory.name),
      "dry_run": True,
      "trading_mode": "spot",
      "strategy": "NostalgiaForInfinityX8",
      "runmode": "dry_run",
      "dry_run_wallet": 10000,
      "db_url": "sqlite:///preserved.sqlite",
      "exchange": {"name": "binance", "key": "private-fixture", "pair_blacklist": ["BNB/.*", "USDC/.*"]},
      "api_server": {"password": "private-fixture"},
    }
    self.rpc = MagicMock()
    self.app = FastAPI()
    self.app.dependency_overrides[api_auth.http_basic_or_jwt_token] = lambda: "test-user"
    self.app.dependency_overrides[get_rpc] = lambda: self.rpc
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      configure_recipe_api(self.app, self.config)
    self.client = TestClient(self.app)
    self.store = RecipeStore(self.config)

  def save(self, settings=None, revision=0):
    return self.client.put("/api/v1/recipe", json={"revision": revision, "settings": settings or DEFAULTS})

  def test_save_persists_without_applying_or_disclosing_credentials(self):
    response = self.save()
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["saved"]["revision"], 1)
    self.assertNotIn("private-fixture", response.text)
    self.assertEqual(RecipeStore(self.config).read()["revision"], 1)
    self.assertEqual((self.store.directory / "saved.json").stat().st_mode & 0o777, 0o600)
    self.assertFalse((self.store.directory / "active.json").exists())
    self.rpc._rpc_reload_config.assert_not_called()

  def test_recipe_requires_authentication(self):
    self.app.dependency_overrides.pop(api_auth.http_basic_or_jwt_token)
    self.app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    self.assertEqual(self.client.get("/api/v1/recipe").status_code, 401)
    self.assertEqual(self.save().status_code, 401)
    self.assertEqual(self.client.post("/api/v1/recipe/apply", json={"revision": 0}).status_code, 401)

  def test_stale_save_and_apply_are_rejected(self):
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save().status_code, 409)
    self.assertEqual(self.client.post("/api/v1/recipe/apply", json={"revision": 0}).status_code, 409)
    self.rpc._rpc_reload_config.assert_not_called()

  def test_invalid_settings_never_change_the_saved_recipe(self):
    for key, value in [
      ("max_open_trades", 50),
      ("max_open_trades", 6.5),
      ("pair_limit", 500),
      ("tradable_balance_ratio", 1),
      ("fee", 0),
      ("max_slippage", 0.9),
      ("min_age_days", 1),
      ("research_pairs", ["BTC/USDT"] * 3),
      ("research_pairs", ["BTC/USDT", "ETH/USDT", "BNB/USDT"]),
      ("research_pairs", ["BTC/USDT", "ETH/USDT", "BTCUP/USDT"]),
      ("research_pairs", ["BTC/USDT", "ETH/USDT", ".*/USDT"]),
      ("dry_run", False),
    ]:
      self.assertEqual(self.save({**DEFAULTS, key: value}).status_code, 422, (key, value))
    self.assertFalse((self.store.directory / "saved.json").exists())
    with self.assertRaises(ValueError):
      RecipeSettings(**{**DEFAULTS, "fee": float("nan")})

  def test_apply_and_restart_preserve_wallet_credentials_database_and_blacklist(self):
    self.save({**DEFAULTS, "max_open_trades": 8, "pair_limit": 60})
    response = self.client.post("/api/v1/recipe/apply", json={"revision": 1})
    self.assertEqual(response.status_code, 200)
    self.rpc._rpc_reload_config.assert_called_once()
    config = deepcopy(self.config)
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      apply_paper_recipe(config)
    self.assertEqual(config["max_open_trades"], 8)
    self.assertEqual(config["pairlists"][-1]["number_assets"], 60)
    for key in ("dry_run_wallet", "db_url", "api_server"):
      self.assertEqual(config[key], self.config[key])
    self.assertEqual(config["exchange"]["key"], "private-fixture")
    self.assertEqual(config["exchange"]["pair_blacklist"], self.config["exchange"]["pair_blacklist"])
    self.assertEqual(config["nfi_recipe_revision"], 1)
    self.assertTrue(config["use_exit_signal"])
    self.assertFalse(config["exit_profit_only"])

  def test_live_mode_and_other_strategies_cannot_apply(self):
    self.config["dry_run"] = False
    self.assertFalse(self.client.get("/api/v1/recipe").json()["can_apply"])
    self.assertEqual(self.client.post("/api/v1/recipe/apply", json={"revision": 0}).status_code, 409)
    self.config["dry_run"] = True
    self.config["strategy"] = "AnotherStrategy"
    self.assertEqual(self.client.post("/api/v1/recipe/apply", json={"revision": 0}).status_code, 409)
    self.rpc._rpc_reload_config.assert_not_called()

  def test_config_hook_is_opt_in_and_research_snapshots_do_not_mutate_main_config(self):
    config = deepcopy(self.config)
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": ""}):
      apply_paper_recipe(config)
    self.assertEqual(config, self.config)
    snapshot = recipe_config(config, self.store.read(), research=True)
    self.assertEqual(len(snapshot["exchange"]["pair_whitelist"]), 40)
    self.assertEqual(snapshot["pairlists"], [{"method": "StaticPairList"}])
    self.assertEqual(config, self.config)
    self.store.save(SaveRecipe(revision=0, settings=RecipeSettings(**{**DEFAULTS, "fee": 0.002})))
    self.assertEqual(snapshot["fee"], 0.001)

  def test_okx_defaults_and_paper_hook_preserve_the_stopped_state(self):
    self.config["exchange"]["name"] = "okx"
    self.config["initial_state"] = "stopped"
    defaults = exchange_defaults(self.config)
    self.assertEqual(len(defaults["research_pairs"]), 40)
    self.assertIn("POL/USDT", defaults["research_pairs"])
    self.assertNotIn("VET/USDT", defaults["research_pairs"])
    self.assertIn("VET/USDT", DEFAULTS["research_pairs"])
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      apply_paper_recipe(self.config)
    self.assertEqual(self.config["initial_state"], "stopped")
    self.assertEqual(self.client.get("/api/v1/recipe").json()["exchange"], "okx")

  def test_failed_atomic_write_preserves_last_good_recipe(self):
    self.save()
    with patch("nfi_research.recipe.os.replace", side_effect=OSError("fixture disk failure")):
      with self.assertRaises(OSError):
        self.store.save(SaveRecipe(revision=1, settings=RecipeSettings(**{**DEFAULTS, "fee": 0.002})))
    self.assertEqual(json.loads((self.store.directory / "saved.json").read_text())["settings"]["fee"], 0.001)
    self.assertFalse(list(self.store.directory.glob(".recipe-*")))


if __name__ == "__main__":
  unittest.main()
