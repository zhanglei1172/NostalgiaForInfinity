import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.webserver_bgwork import ApiBG
from nfi_research.preparation import configure_worker
from nfi_research.recipe import DEFAULTS, RecipeSettings, RecipeStore, SaveRecipe


class WorkerRecipeTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.config = {
      "user_data_dir": Path(self.directory.name),
      "exchange": {"name": "binance"},
      "stake_currency": "USDT",
      "dry_run_wallet": 10000,
      "max_open_trades": 6,
    }
    self.store = RecipeStore(self.config)
    self.app = FastAPI()
    self.app.dependency_overrides[api_auth.http_basic_or_jwt_token] = lambda: "worker-user"

  def test_saved_fields_reach_the_engine_and_changed_pairs_invalidate_cached_data(self):
    start = AsyncMock(return_value={"status": "running"})
    with (
      patch("freqtrade.rpc.api_server.api_backtest.api_start_backtest", start),
      patch("freqtrade.rpc.api_server.api_backtest.api_delete_backtest") as reset,
      patch("nfi_research.preparation.Preparation.validate_timeframe"),
      patch.object(ApiBG, "analysis_running", False),
    ):
      configure_worker(self.app, self.config)
      client = TestClient(self.app)
      self.store.save(
        SaveRecipe(
          revision=0,
          settings=RecipeSettings(
            **{
              **DEFAULTS,
              "fee": 0.002,
              "tradable_balance_ratio": 0.9,
              "max_slippage": 0.01,
              "max_open_trades": 8,
              "research_pairs": ["BTC/USDT", "ETH/USDT", "XRP/USDT"],
            }
          ),
        )
      )
      self.assertEqual(client.get("/api/v1/research-info").json()["recipe_revision"], 1)
      response = client.post(
        "/api/v1/research-backtest",
        json={
          "strategy": "NostalgiaForInfinityX8",
          "enable_protections": True,
          "timerange": "20250101-20250201",
          "dry_run_wallet": 15000,
          "max_open_trades": 99,
          "timeframe": "1h",
        },
      )
      self.assertEqual(response.status_code, 200)
      reset.assert_called_once()
      snapshot = start.call_args.kwargs["config"]
      self.assertEqual(snapshot["fee"], 0.002)
      self.assertEqual(snapshot["tradable_balance_ratio"], 0.9)
      self.assertEqual(snapshot["nfi_parameters"]["max_slippage"], 0.01)
      self.assertEqual(snapshot["exchange"]["pair_whitelist"], ["BTC/USDT", "ETH/USDT", "XRP/USDT"])
      self.assertEqual(start.call_args.args[0].max_open_trades, 8)
      self.assertEqual(start.call_args.args[0].timeframe, "5m")
      self.assertEqual(start.call_args.args[0].dry_run_wallet, 15000)
      exported = snapshot["original_config"]
      self.assertEqual(exported["nfi_recipe_revision"], 1)
      self.assertEqual(exported["nfi_parameters"]["max_slippage"], 0.01)
      self.assertEqual(exported["dry_run_wallet"], 15000)
      self.assertEqual(exported["timerange"], "20250101-20250201")
      self.assertEqual(exported["exchange"]["pair_whitelist"], snapshot["exchange"]["pair_whitelist"])
      self.assertNotIn("fee", self.config)

  def test_running_backtest_blocks_download_and_second_backtest(self):
    configure_worker(self.app, self.config)
    client = TestClient(self.app)
    with patch.object(ApiBG, "analysis_running", True):
      self.assertEqual(
        client.post(
          "/api/v1/research-prepare",
          json={
            "start_date": "2025-01-01",
            "end_date": "2025-02-01",
          },
        ).status_code,
        409,
      )
      self.assertEqual(
        client.post(
          "/api/v1/research-backtest",
          json={"strategy": "NostalgiaForInfinityX8", "enable_protections": True, "timerange": "20250101-20250201"},
        ).status_code,
        409,
      )

  def test_missing_pair_history_blocks_the_engine_instead_of_silently_dropping_pairs(self):
    start = AsyncMock()
    with (
      patch("freqtrade.rpc.api_server.api_backtest.api_start_backtest", start),
      patch("nfi_research.preparation.Preparation.validate_timeframe", side_effect=ValueError("missing pair")),
      patch.object(ApiBG, "analysis_running", False),
    ):
      configure_worker(self.app, self.config)
      response = TestClient(self.app).post(
        "/api/v1/research-backtest",
        json={"strategy": "NostalgiaForInfinityX8", "enable_protections": True, "timerange": "20250101-20250201"},
      )
      self.assertEqual(response.status_code, 409)
      self.assertEqual(response.json()["detail"], "research_data_required")
      start.assert_not_called()

  def test_changed_recipe_invalidates_the_previous_download_success_status(self):
    def finish(worker, payload):
      worker.status.update(running=False, status="success")

    configure_worker(self.app, self.config)
    client = TestClient(self.app)
    # Initial info binds the default recipe snapshot.
    client.get("/api/v1/research-info")
    with patch("nfi_research.preparation.Preparation.run", finish), patch.object(ApiBG, "analysis_running", False):
      self.assertEqual(
        client.post(
          "/api/v1/research-prepare", json={"start_date": "2025-01-01", "end_date": "2025-02-01"}
        ).status_code,
        200,
      )
    self.assertEqual(client.get("/api/v1/research-info").json()["preparation"]["status"], "success")
    self.store.save(SaveRecipe(revision=0, settings=RecipeSettings(**{**DEFAULTS, "fee": 0.002})))
    info = client.get("/api/v1/research-info").json()
    self.assertEqual(info["recipe_revision"], 1)
    self.assertEqual(info["preparation"]["status"], "idle")


if __name__ == "__main__":
  unittest.main()
