import base64
import json
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api
from nfi_research import allowed, configure_research_api
from nfi_research.preparation import Preparation, PrepareRequest


class GatewayTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.config = {
      "user_data_dir": self.directory.name,
      "api_server": {
        "username": "paper",
        "password": "fixture-service-password",
        "jwt_secret_key": "isolated-research-test-signing-key",
      },
    }
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    configure_account_api(app, self.config)
    with patch.dict("os.environ", {"NFI_RESEARCH_URL": "http://backtesting:8080"}):
      configure_research_api(app, self.config)
    self.client = TestClient(app)
    self.headers = {"Authorization": "Basic " + base64.b64encode(b"paper:fixture-service-password").decode()}

  def test_research_requires_main_account_authentication(self):
    self.assertEqual(self.client.get("/api/v1/research/info").status_code, 401)

  def test_gateway_blocks_trading_controls_and_path_injection(self):
    for method, path in [
      ("POST", "forceenter"),
      ("POST", "account/password"),
      ("GET", "../show_config"),
      ("DELETE", "backtest/history/result"),
      ("GET", "strategy/../../logs"),
    ]:
      self.assertFalse(allowed(method, path))
    self.assertEqual(self.client.post("/api/v1/research/forceenter", headers=self.headers).status_code, 404)

  def test_wallet_history_is_read_only_and_accepts_only_a_result_stem_and_strategy_name(self):
    path = "backtest/history/backtest-result-2025-01-01_00-00-00/NostalgiaForInfinityX8/wallet"
    self.assertTrue(allowed("GET", path))
    for method, invalid in (
      ("POST", path),
      ("DELETE", path),
      ("GET", "backtest/history/../config/wallet"),
      ("GET", "backtest/history/result/NostalgiaForInfinityX8/pair_history"),
      ("GET", "backtest/history/file/NostalgiaForInfinityX8/../../show_config"),
    ):
      self.assertFalse(allowed(method, invalid))
    original = httpx.AsyncClient
    captured = []

    def respond(request):
      captured.append(request)
      return httpx.Response(
        200, json={"columns": ["__date_ts", "total_quote"], "data": [[1735689600000, 10000]], "length": 1}
      )

    with patch(
      "nfi_research.httpx.AsyncClient", side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    ):
      self.assertEqual(self.client.get("/api/v1/research/" + path).status_code, 401)
      response = self.client.get("/api/v1/research/" + path, headers=self.headers)
      self.assertEqual(response.status_code, 200)
    self.assertEqual(str(captured[0].url), "http://backtesting:8080/api/v1/" + path)
    self.assertEqual(captured[0].headers["Authorization"], self.headers["Authorization"])

  def test_gateway_uses_service_auth_and_preserves_query_and_body(self):
    captured = []

    def respond(request):
      captured.append(request)
      return httpx.Response(200, json={"strategies": ["NostalgiaForInfinityX8"]})

    original = httpx.AsyncClient
    token = api_auth.create_token({"identity": {"u": "paper"}}, self.config["api_server"]["jwt_secret_key"])
    browser_headers = {"Authorization": "Bearer " + token}
    with patch(
      "nfi_research.httpx.AsyncClient", side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    ):
      response = self.client.get("/api/v1/research/strategies", headers=browser_headers)
      self.assertEqual(response.status_code, 200)
      payload = {"strategy": "NostalgiaForInfinityX8", "timerange": "20250101-20250201", "enable_protections": True}
      response = self.client.post("/api/v1/research/backtest", headers=browser_headers, json=payload)
      self.assertEqual(response.status_code, 200)
      self.client.get(
        "/api/v1/research/backtest/history/result",
        headers=browser_headers,
        params={"filename": "backtest-2025", "strategy": "NostalgiaForInfinityX8"},
      )
    self.assertEqual(str(captured[0].url), "http://backtesting:8080/api/v1/strategies")
    self.assertEqual(captured[0].headers["Authorization"], self.headers["Authorization"])
    self.assertNotEqual(captured[0].headers["Authorization"], browser_headers["Authorization"])
    self.assertEqual(json.loads(captured[1].content), payload)
    self.assertEqual(str(captured[1].url), "http://backtesting:8080/api/v1/research-backtest")
    self.assertEqual(captured[2].url.params["filename"], "backtest-2025")

  def test_worker_auth_failure_does_not_log_main_account_out(self):
    original = httpx.AsyncClient
    with patch(
      "nfi_research.httpx.AsyncClient",
      side_effect=lambda **kw: original(transport=httpx.MockTransport(lambda _: httpx.Response(401)), **kw),
    ):
      response = self.client.get("/api/v1/research/info", headers=self.headers)
    self.assertEqual(response.status_code, 502)
    self.assertEqual(response.json()["detail"], "research_service_auth_failed")

  def test_unconfigured_live_management_proxies_with_independent_service_auth_and_no_local_worker(self):
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    self.config["runmode"] = "webserver"
    captured = []

    def respond(request):
      captured.append(request)
      return httpx.Response(200, json={"strategies": ["NostalgiaForInfinityX8"]})

    original = httpx.AsyncClient
    with (
      patch.dict(
        "os.environ",
        {
          "NFI_RECIPE_ROLE": "live",
          "NFI_RESEARCH_URL": "http://backtesting:8080",
          "NFI_RESEARCH_USERNAME": "research-service",
          "NFI_RESEARCH_PASSWORD": "fixture-research-password",
        },
      ),
      patch("nfi_research.configure_worker") as worker,
      patch(
        "nfi_research.httpx.AsyncClient",
        side_effect=lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
      ),
    ):
      configure_research_api(app, self.config)
      client = TestClient(app)
      self.assertEqual(client.get("/api/v1/research/strategies").status_code, 401)
      response = client.get("/api/v1/research/strategies", headers=self.headers)
      self.assertEqual(response.status_code, 200)
      self.assertEqual(client.post("/api/v1/research/start", headers=self.headers).status_code, 404)
      self.assertEqual(client.post("/api/v1/research-backtest", headers=self.headers).status_code, 404)
      worker.assert_not_called()
    expected = "Basic " + base64.b64encode(b"research-service:fixture-research-password").decode()
    self.assertEqual(captured[0].headers["Authorization"], expected)
    self.assertNotIn("fixture-research-password", response.text)


class PreparationTests(unittest.TestCase):
  def setUp(self):
    self.config = {
      "exchange": {"name": "binance", "pair_whitelist": ["BTC/USDT"]},
      "datadir": "/tmp",
      "stake_currency": "USDT",
      "dry_run_wallet": 10000,
      "max_open_trades": 6,
    }
    self.payload = PrepareRequest(start_date="2025-01-01", end_date="2025-02-01")

  def test_invalid_future_and_reversed_dates_are_rejected(self):
    for start, end in [("2025-02-01", "2025-01-01"), ("2025-01-01", "2099-01-01"), ("2020-01-01", "2025-01-01")]:
      with self.assertRaises(ValueError):
        PrepareRequest(start_date=start, end_date=end)

  def test_each_timeframe_gets_its_own_warmup_and_both_ends_extend_without_erasing(self):
    worker = Preparation(self.config)
    worker.start(self.payload)
    calls = []

    def download(config, exchange):
      calls.append((config["timeframes"][0], config["timerange"], config["prepend_data"], config["erase"]))

    handler = MagicMock()
    handler.ohlcv_data_min_max.return_value = (
      datetime(2020, 1, 1, tzinfo=UTC),
      datetime(2025, 2, 1, tzinfo=UTC),
      1000,
    )
    with (
      patch("freqtrade.rpc.api_server.deps.get_exchange"),
      patch("freqtrade.data.history.history_utils.download_data", side_effect=download),
      patch("freqtrade.data.history.datahandlers.get_datahandler", return_value=handler),
    ):
      worker.run(self.payload)
    self.assertEqual(worker.info()["preparation"]["status"], "success")
    self.assertEqual(len(calls), 10)
    self.assertEqual(calls[0], ("5m", "20241228-20250201", True, False))
    self.assertEqual(calls[1][2], False)
    self.assertEqual(calls[-1][0], "1d")
    self.assertTrue(calls[-1][1].startswith("20220716"))
    self.assertEqual(self.config["stake_currency"], "USDT")

  def test_incomplete_candles_fail_instead_of_reporting_success(self):
    worker = Preparation(self.config)
    worker.start(self.payload)
    with (
      patch("freqtrade.rpc.api_server.deps.get_exchange"),
      patch("freqtrade.data.history.history_utils.download_data"),
      patch("freqtrade.data.history.datahandlers.get_datahandler", side_effect=ValueError("no candles")),
    ):
      worker.run(self.payload)
    self.assertEqual(worker.status["status"], "failed")
    self.assertFalse(worker.status["running"])

  def test_duplicate_downloads_are_rejected(self):
    worker = Preparation(self.config)
    worker.start(self.payload)
    with self.assertRaises(HTTPException) as error:
      worker.start(self.payload)
    self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
  unittest.main()
