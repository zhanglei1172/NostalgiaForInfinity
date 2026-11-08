import logging
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.enums import State
from freqtrade.persistence import Order, Trade, init_db
from freqtrade.rpc.api_server.deps import get_api_config, get_rpc
from nfi_research.activity import (
  RejectionJournal,
  activity_snapshot,
  configure_activity_api,
  install_journal,
  pair_snapshot,
  recent_fills,
)


class ActivityTests(unittest.TestCase):
  def setUp(self):
    self.now = datetime.now(UTC)
    self.bot = MagicMock()
    self.bot.config = {"exchange": {"name": "okx"}, "dry_run": True, "strategy": "NostalgiaForInfinityX8"}
    self.bot.strategy.timeframe = "5m"
    self.bot.state = State.STOPPED
    self.bot.active_pair_whitelist = ["BTC/USDT"]
    self.bot.get_free_open_trades.return_value = 6
    self.bot.dataprovider.get_analyzed_dataframe.return_value = (pd.DataFrame(), self.now)
    self.journal = RejectionJournal()

  def test_stopped_and_paused_are_distinct_and_snapshot_never_drives_the_bot(self):
    with (
      patch("nfi_research.activity.PairLocks.get_pair_longest_lock", return_value=None),
      patch("nfi_research.activity.Trade.get_open_trades", return_value=[]),
      patch("nfi_research.activity.recent_fills", return_value=[]),
    ):
      result = activity_snapshot(self.bot, self.journal)
      self.assertEqual(result["reasons"], ["stopped"])
      self.assertEqual(result["pairs"][0]["reasons"], ["stopped", "no_analysis"])
      self.bot.state = State.PAUSED
      self.assertEqual(activity_snapshot(self.bot, self.journal)["reasons"], ["paused"])
      self.bot.state = State.RUNNING
      self.bot.get_free_open_trades.return_value = 0
      self.assertEqual(activity_snapshot(self.bot, self.journal)["reasons"], ["slots_full"])
    self.bot.strategy.analyze.assert_not_called()
    self.bot.strategy.get_entry_signal.assert_not_called()
    self.bot.wallets.update.assert_not_called()
    self.bot.exchange.create_order.assert_not_called()

  def test_raw_entry_is_not_an_order_and_conflicting_stale_and_locked_facts_are_exposed(self):
    frame = pd.DataFrame(
      [{"date": self.now - timedelta(minutes=30), "enter_long": 1, "exit_long": 1, "enter_tag": "120"}]
    )
    self.bot.dataprovider.get_analyzed_dataframe.return_value = (frame, self.now)
    lock = SimpleNamespace(lock_end_time=self.now + timedelta(minutes=5))
    with patch("nfi_research.activity.PairLocks.get_pair_longest_lock", return_value=lock):
      value = pair_snapshot(self.bot, "BTC/USDT", self.now, ["stopped"], {"BTC/USDT"})
    self.assertEqual(value["signal"], "conflict")
    self.assertEqual(value["entry_tag"], "120")
    self.assertEqual(value["reasons"], ["stopped", "position_open", "pair_locked", "stale_candle", "signal_conflict"])
    frame.loc[0, "exit_long"] = 0
    frame.loc[0, "date"] = self.now
    with patch("nfi_research.activity.PairLocks.get_pair_longest_lock", return_value=None):
      value = pair_snapshot(self.bot, "BTC/USDT", self.now, [], set())
    self.assertEqual(value["signal"], "entry")
    self.assertEqual(value["reasons"], ["entry_candidate"])

  def test_journal_whitelists_reasons_bounds_memory_and_omits_raw_logs(self):
    def emit(text):
      self.journal.emit(logging.LogRecord("NostalgiaForInfinityX8", logging.WARNING, "", 0, text, (), None))

    emit("API Secret: private-fixture")
    emit("[time] Cancelling entry for BTC/USDT due to slippage 2.15%")
    emit("User denied entry for BTC/USDT.")
    self.assertEqual([e["reason"] for e in self.journal.snapshot()], ["slippage"])
    emit("[time] Cancelling entry for ETH/USDT due to not being in grind mode coins list.")
    emit("[time] Cancelling entry for XRP/USDT due to grind mode slots limit reached.")
    emit("[time] Cancelling entry for SOL/USDT due to not being in top coins list.")
    emit("[time] Cancelling entry for ADA/USDT due to insufficient free slots.")
    self.assertEqual(self.journal.snapshot()[0]["reason"], "mode_slots")
    emit("[time] Cancelling entry for BTC/USDT due to private-fixture")
    self.assertNotIn("private-fixture", str(self.journal.snapshot()))
    for _ in range(120):
      emit("User denied entry for ETH/USDT.")
    self.assertEqual(len(self.journal.snapshot()), 100)

  def test_journal_reinstallation_does_not_duplicate_handlers(self):
    install_journal()
    latest = install_journal()
    for name in ("NostalgiaForInfinityX8", "freqtrade.freqtradebot"):
      logger = logging.getLogger(name)
      handlers = [h for h in logger.handlers if isinstance(h, RejectionJournal)]
      self.assertEqual(handlers, [latest])
      logger.removeHandler(latest)

  def test_endpoint_requires_authentication_and_is_read_only(self):
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: {"username": "test-user", "password": "test-password"}
    app.dependency_overrides[get_rpc] = lambda: SimpleNamespace(_freqtrade=self.bot)
    configure_activity_api(app, {"runmode": "dry_run"})
    with TestClient(app) as client:
      self.assertEqual(client.get("/api/v1/strategy-activity").status_code, 401)
      with patch("nfi_research.activity.activity_snapshot", return_value={"reasons": ["stopped"]}):
        response = client.get("/api/v1/strategy-activity", auth=("test-user", "test-password"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reasons"], ["stopped"])
      self.assertEqual(client.post("/api/v1/strategy-activity").status_code, 405)

  def test_fills_use_real_order_tags_and_only_the_final_exit_gets_the_trade_exit_reason(self):
    init_db("sqlite://")
    self.addCleanup(Trade.session.remove)
    trade = Trade(
      pair="BTC/USDT",
      exchange="okx",
      is_open=False,
      is_short=False,
      amount=1,
      open_rate=100,
      stake_amount=100,
      fee_open=0.001,
      fee_close=0.001,
      open_date=self.now,
      enter_tag="original-entry",
      exit_reason="final-exit",
    )
    trade.orders = [
      Order(
        ft_order_side="buy",
        ft_pair="BTC/USDT",
        ft_amount=1,
        ft_price=100,
        ft_is_open=False,
        order_id="1",
        side="buy",
        filled=1,
        price=100,
        order_filled_date=self.now,
        ft_order_tag="initial",
      ),
      Order(
        ft_order_side="sell",
        ft_pair="BTC/USDT",
        ft_amount=1,
        ft_price=100,
        ft_is_open=False,
        order_id="2",
        side="sell",
        filled=0.4,
        price=110,
        order_filled_date=self.now + timedelta(seconds=1),
        ft_order_tag="partial",
      ),
      Order(
        ft_order_side="stoploss",
        ft_pair="BTC/USDT",
        ft_amount=1,
        ft_price=100,
        ft_is_open=False,
        order_id="3",
        side="sell",
        filled=0.6,
        price=120,
        order_filled_date=self.now + timedelta(seconds=2),
      ),
      Order(
        ft_order_side="buy",
        ft_pair="BTC/USDT",
        ft_amount=1,
        ft_price=100,
        ft_is_open=False,
        order_id="4",
        side="buy",
        filled=0,
        price=100,
        order_date=self.now + timedelta(seconds=3),
      ),
    ]
    # The final stop is placed first and fills last, after a partial reduction.
    trade.orders.insert(0, trade.orders.pop(2))
    Trade.session.add(trade)
    Trade.session.commit()
    fills = recent_fills()
    self.assertEqual(len(fills), 3)
    self.assertEqual([f["tag"] for f in fills], [None, "partial", "initial"])
    self.assertEqual([f["exit_reason"] for f in fills], ["final-exit", None, None])


if __name__ == "__main__":
  unittest.main()
