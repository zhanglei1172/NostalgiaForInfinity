import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.enums import CandleType
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.webserver_bgwork import ApiBG
from nfi_live.storage import atomic_json
from nfi_live.trading import LEVERAGE_KEYS, public_research_snapshot
from nfi_research.preparation import Preparation, PrepareRequest, configure_worker
from nfi_research.recipe import DEFAULTS


class InstanceResearchTests(unittest.TestCase):
  def test_instance_backtest_uses_applied_public_snapshot_without_service_credentials(self):
    with tempfile.TemporaryDirectory() as name:
      directory = Path(name)
      profile = {
        "trading_mode": "futures",
        "nfi_live_leverage": 2,
        "available_capital": 1500,
        "exchange": {"key": "private-exchange-key"},
      }
      recipe = {
        "schema_version": 1,
        "revision": 12,
        "settings": {**DEFAULTS, "research_pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"]},
      }
      atomic_json(directory / "snapshot.json", public_research_snapshot(profile, recipe))
      config = {
        "user_data_dir": directory,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "stake_currency": "USDT",
        "dry_run_wallet": 10000,
        "max_open_trades": 6,
        "exchange": {"name": "okx", "key": "", "secret": ""},
        "api_server": {"username": "internal", "password": "private-service-password"},
      }
      start = AsyncMock(return_value={"status": "running"})
      app = FastAPI()
      app.dependency_overrides[api_auth.http_basic_or_jwt_token] = lambda: "worker-user"
      with (
        patch.dict(os.environ, {"NFI_RESEARCH_INSTANCE_DIR": name}),
        patch("freqtrade.rpc.api_server.api_backtest.api_start_backtest", start),
        patch("freqtrade.rpc.api_server.api_backtest.api_delete_backtest"),
        patch("nfi_research.preparation.Preparation.validate_timeframe"),
        patch("nfi_research.preparation.Preparation.validate_futures_data"),
        patch.object(ApiBG, "analysis_running", False),
      ):
        configure_worker(app, config)
        client = TestClient(app)
        info = client.get("/api/v1/research-info").json()
        self.assertEqual(info["scope"], "instance")
        self.assertEqual(info["trading_mode"], "futures")
        self.assertEqual(info["leverage"], 2)
        self.assertEqual(info["starting_balance"], 1500)
        self.assertEqual(info["recipe_revision"], 12)
        response = client.post(
          "/api/v1/research-backtest",
          json={"strategy": "NostalgiaForInfinityX8", "timerange": "20250101-20250201", "enable_protections": True},
        )
        self.assertEqual(response.status_code, 200)
        snapshot = start.call_args.kwargs["config"]
        self.assertEqual(snapshot["exchange"]["pair_whitelist"], ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"])
        self.assertEqual(snapshot["tradable_balance_ratio"], 1)
        self.assertTrue(all(snapshot["nfi_parameters"][key] == 2 for key in LEVERAGE_KEYS))
        exported = snapshot["original_config"]
        self.assertEqual(exported["exchange"]["name"], "okx")
        self.assertEqual(exported["margin_mode"], "isolated")
        self.assertNotIn("api_server", exported)
        self.assertNotIn("private-service-password", str(exported))
        self.assertNotIn("private-exchange-key", str(snapshot))
        atomic_json(directory / "snapshot.json", public_research_snapshot({"trading_mode": "spot"}, recipe))
        self.assertEqual(client.get("/api/v1/research-info").status_code, 409)

  def test_futures_requires_mark_and_funding_history_but_accepts_eight_hour_events(self):
    config = {"trading_mode": "futures", "datadir": "/tmp", "exchange": {"pair_whitelist": ["BTC/USDT:USDT"]}}
    payload = PrepareRequest(start_date="2025-01-01", end_date="2025-01-03")
    handler = MagicMock()

    def history(pair, timeframe, candle_type, **kwargs):
      return pd.DataFrame(
        {
          "date": pd.date_range(
            "2025-01-01", "2025-01-03", freq="8h" if candle_type == CandleType.FUNDING_RATE else "1h", tz="UTC"
          )
        }
      )

    handler.ohlcv_load.side_effect = history
    with patch("freqtrade.data.history.datahandlers.get_datahandler", return_value=handler):
      Preparation.validate_futures_data(config, payload)
      handler.ohlcv_load.side_effect = None
      handler.ohlcv_load.return_value = pd.DataFrame()
      with self.assertRaises(ValueError):
        Preparation.validate_futures_data(config, payload)
      handler.ohlcv_load.return_value = pd.DataFrame(
        {"date": pd.to_datetime([datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 3, tzinfo=UTC)])}
      )
      with self.assertRaises(ValueError):
        Preparation.validate_futures_data(config, payload)


if __name__ == "__main__":
  unittest.main()
