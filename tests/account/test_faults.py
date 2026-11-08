import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ccxt
from freqtrade.exceptions import TemporaryError
from freqtrade.exchange.common import retrier, retrier_async
from nfi_account.faults import FaultJournal, failure_code, journal_for, operational_snapshot, wrap_method


class FaultObserverTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.config = {"user_data_dir": Path(self.directory.name)}
    self.exchange = SimpleNamespace(_config=self.config, name="OKX")
    self.journal = journal_for(self.directory.name)
    self.clock = 1000000.0
    self.journal.now = lambda: self.clock
    self.role = patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"})
    self.role.start()
    self.addCleanup(self.role.stop)

  def test_return_value_and_exception_identity_are_preserved_without_an_extra_call(self):
    result = {"status": "open", "id": "fixture-order"}
    calls = []

    def create(exchange, **kwargs):
      calls.append(kwargs)
      return result

    wrapped = wrap_method(create, "create_order")
    self.assertIs(wrapped(self.exchange, pair="BTC/USDT", side="buy"), result)
    self.assertEqual(len(calls), 1)
    error = ccxt.InsufficientFunds("fixture-api-key fixture-secret fixture-passphrase")

    def fail(exchange, **kwargs):
      raise error

    with self.assertRaises(ccxt.InsufficientFunds) as raised:
      wrap_method(fail, "create_order")(self.exchange, pair="BTC/USDT")
    self.assertIs(raised.exception, error)
    snapshot = self.journal.snapshot()
    self.assertEqual(snapshot["trades"][0]["code"], "insufficient_funds")
    for secret in ("fixture-api-key", "fixture-secret", "fixture-passphrase"):
      self.assertNotIn(secret, str(snapshot))

  def test_internal_retries_that_succeed_do_not_create_incidents(self):
    attempts = []

    @retrier(retries=2)
    def fetch(exchange):
      attempts.append(1)
      if len(attempts) < 3:
        raise TemporaryError("fixture-private-response")
      return {"USDT": {"free": 100}}

    result = wrap_method(fetch, "get_balances")(self.exchange)
    self.assertEqual(result["USDT"]["free"], 100)
    self.assertEqual(len(attempts), 3)
    self.assertFalse(next(iter(self.journal.snapshot()["observations"].values()))["active"])
    self.assertEqual(self.journal.snapshot()["trades"], [])

  def test_async_final_failure_and_success_are_observed_per_pair_and_timeframe(self):
    attempts = []

    @retrier_async
    async def fail(exchange, pair, timeframe):
      attempts.append(1)
      raise TemporaryError("fixture-secret")

    with self.assertRaises(TemporaryError):
      asyncio.run(wrap_method(fail, "_async_get_candle_history")(self.exchange, "BTC/USDT", "5m"))
    self.assertGreater(len(attempts), 1)
    snapshot = self.journal.snapshot()
    self.assertEqual(len(snapshot["observations"]), 1)
    self.assertTrue(snapshot["observations"]["_async_get_candle_history:BTC/USDT:5m"]["active"])

    async def ok(exchange, pair, timeframe):
      return (pair, timeframe, [])

    wrapped = wrap_method(ok, "_async_get_candle_history")
    asyncio.run(wrapped(self.exchange, "ETH/USDT", "5m"))
    self.assertTrue(self.journal.snapshot()["observations"]["_async_get_candle_history:BTC/USDT:5m"]["active"])
    asyncio.run(wrapped(self.exchange, "BTC/USDT", "5m"))
    self.assertFalse(self.journal.snapshot()["observations"]["_async_get_candle_history:BTC/USDT:5m"]["active"])

  def test_network_order_failure_is_uncertain_and_never_retried_by_observer(self):
    calls = []

    def fail(exchange, **kwargs):
      calls.append(1)
      raise ccxt.RequestTimeout("fixture-secret")

    with self.assertRaises(ccxt.RequestTimeout):
      wrap_method(fail, "create_order")(self.exchange, pair="ETH/USDT")
    self.assertEqual(len(calls), 1)
    snapshot = self.journal.snapshot()
    self.assertEqual(snapshot["trades"][0]["code"], "order_uncertain")
    self.assertEqual(snapshot["observations"]["create_order:ETH/USDT:"]["code"], "connection")

  def test_sanitization_bounds_and_typed_authentication_and_rate_limit_classification(self):
    self.assertEqual(failure_code(ccxt.AuthenticationError("private")), "authentication")
    self.assertEqual(failure_code(ccxt.RateLimitExceeded("private")), "rate_limited")
    journal = FaultJournal()
    journal.record("get_balances", pair="https://private-api-key", code="authentication")
    self.assertIsNone(next(iter(journal.snapshot()["observations"].values()))["pair"])
    for index in range(400):
      journal.record("fetch_ticker", f"PAIR{index}/USDT", code="connection", trade=True)
    self.assertEqual(len(journal.snapshot()["observations"]), 256)
    self.assertEqual(len(journal.snapshot()["trades"]), 64)

  def test_live_initialization_failure_survives_fallback_to_the_management_server(self):
    from nfi_live.storage import atomic_json

    status = Path(self.directory.name) / ".nfi-live-status.json"
    atomic_json(status, {"phase": "error", "revision": 1, "error": "live_start_failed"})
    snapshot = operational_snapshot(self.config, "live")
    self.assertEqual(snapshot["observations"]["initialization::"]["code"], "initialization")
    atomic_json(status, {"phase": "ready", "revision": 1, "error": None})
    self.assertFalse(operational_snapshot(self.config, "live")["observations"]["initialization::"]["active"])
