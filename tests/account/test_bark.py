import json
import os
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api
from nfi_account.bark import BarkMonitor, BarkStore, SaveBark, destination_parts, profit_snapshot, send_bark
from nfi_account.credentials import AccountError


class BarkTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.password = "fixture-bark-admin-password"
    self.destination = "https://bark.fixture.test/fixture-private-device"
    self.config = {
      "user_data_dir": self.directory,
      "api_server": {"username": "paper", "password": self.password, "jwt_secret_key": "fixture-only-secret"},
    }
    self.app, self.client = self.make_app()
    self.store = BarkStore(self.directory)
    self.value = {"roi_pct": 0.0, "bot_state": "stopped"}
    self.clock = 100000.0
    self.send = Mock()
    self.monitor = BarkMonitor(self.store, "paper", lambda: self.value, self.send, lambda: self.clock)

  def make_app(self, role="paper", **kwargs):
    app = FastAPI(**kwargs)
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": role}):
      configure_account_api(app, self.config)
    client = TestClient(app)
    client.auth = ("paper", self.password)
    return app, client

  def save(self, **changes):
    body = {"enabled": True, "destination": self.destination, "revision": 0, "current_password": self.password}
    body.update(changes)
    return self.client.put("/api/v1/bark-settings", json=body)

  def tick(self, roi=None, state=None, seconds=60):
    self.clock += seconds
    if roi is not None:
      self.value["roi_pct"] = roi
    if state is not None:
      self.value["bot_state"] = state
    self.monitor.tick()

  def test_private_defaults_authenticated_save_and_test(self):
    self.client.auth = None
    self.assertEqual(self.client.get("/api/v1/bark-settings").status_code, 401)
    self.client.auth = ("paper", self.password)
    self.assertFalse(self.client.get("/api/v1/bark-settings").json()["enabled"])
    self.assertFalse(self.store.path.exists())
    result = self.save(enabled=False)
    self.assertEqual(result.status_code, 200, result.text)
    self.assertTrue(result.json()["destination_configured"])
    self.assertNotIn("fixture-private-device", result.text)
    self.assertNotIn(self.password, self.store.path.read_text())
    self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
    with patch.object(self.app.state.bark_monitor, "send") as sender:
      result = self.client.post("/api/v1/bark-settings/test", json={"revision": 1, "current_password": self.password})
      self.assertEqual(result.status_code, 200, result.text)
      self.assertEqual(sender.call_count, 1)
      self.assertEqual(result.json()["history"][0]["event"], "test")
      result = self.client.post("/api/v1/bark-settings/test", json={"revision": 1, "current_password": self.password})
      self.assertEqual(result.status_code, 429)
      self.assertEqual(sender.call_count, 1)

  def test_wrong_password_validation_origin_and_stale_revision(self):
    self.assertEqual(self.save(current_password="wrong").status_code, 400)
    for changes in (
      {"profit_threshold_pct": -1},
      {"loss_threshold_pct": 101},
      {"cooldown_minutes": 0},
      {"enabled": "true"},
      {"extra": self.destination},
      {"profit_threshold_pct": "NaN"},
    ):
      result = self.save(**changes)
      self.assertEqual(result.status_code, 400)
      self.assertNotIn(self.password, result.text)
      self.assertNotIn("fixture-private-device", result.text)
    for url in (
      "file:///etc/passwd",
      "https://bark.fixture.test/",
      "https://user:pass@bark.fixture.test/key",
      "https://bark.fixture.test/key?secret=key",
      "https://bark.fixture.test/../key",
      "https://bark.fixture.test/%0a/key",
      "https://bark.fixture.test:/key",
    ):
      result = self.save(destination=url)
      self.assertEqual(result.status_code, 400, url)
    result = self.client.put(
      "/api/v1/bark-settings",
      headers={"Origin": "https://evil.test"},
      json={"revision": 0, "current_password": self.password},
    )
    self.assertEqual(result.status_code, 403)
    self.assertFalse(self.store.path.exists())
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save().status_code, 409)
    self.assertEqual(
      self.client.post(
        "/api/v1/bark-settings/test", json={"revision": 0, "current_password": self.password}
      ).status_code,
      409,
    )

  def test_destination_retention_clearing_rules_and_independent_bots(self):
    self.assertEqual(self.save(profit_enabled=False, loss_enabled=False).status_code, 400)
    self.assertEqual(self.save(destination="").status_code, 400)
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save(revision=1, destination="", cooldown_minutes=30).status_code, 200)
    self.assertEqual(self.store.read()["destination"], self.destination)
    self.assertEqual(self.save(revision=2, destination="", clear_destination=True).status_code, 400)
    self.assertEqual(self.save(revision=2, destination="", clear_destination=True, enabled=False).status_code, 200)
    self.assertEqual(self.store.read()["destination"], "")
    self.assertFalse(BarkStore(self.directory / "another-bot").read()["settings"]["enabled"])
    self.assertEqual(self.make_app("live")[1].get("/api/v1/bark-settings").json()["role"], "live")
    self.assertEqual(self.make_app("")[1].get("/api/v1/bark-settings").status_code, 404)

  def test_live_bark_save_and_test_work_behind_a_same_origin_reverse_proxy(self):
    self.app, self.client = self.make_app("live")
    self.client.headers.update({"Origin": "https://console.example.test", "Sec-Fetch-Site": "same-origin"})
    result = self.save(enabled=False)
    self.assertEqual(result.status_code, 200, result.text)
    self.assertEqual(result.json()["role"], "live")
    with patch.object(self.app.state.bark_monitor, "send") as sender:
      result = self.client.post("/api/v1/bark-settings/test", json={"revision": 1, "current_password": self.password})
      self.assertEqual(result.status_code, 200, result.text)
      sender.assert_called_once()
    self.client.headers["Sec-Fetch-Site"] = "cross-site"
    rejected = self.save(enabled=False, revision=1)
    self.assertEqual(rejected.status_code, 403)
    self.assertEqual(rejected.json()["detail"], "bark_origin_rejected")
    self.assertEqual(self.store.read()["revision"], 1)

  def test_profit_loss_crossings_cooldown_and_restart_deduplication(self):
    self.assertEqual(self.save().status_code, 200)
    self.tick(4.999)
    self.send.assert_not_called()
    self.tick(5.0)
    self.assertEqual(self.send.call_count, 1)
    # Recreate the monitor, as occurs on container restart or a worker reload.
    self.monitor = BarkMonitor(BarkStore(self.directory), "paper", lambda: self.value, self.send, lambda: self.clock)
    self.tick(6, seconds=7200)
    self.assertEqual(self.send.call_count, 1)
    self.tick(4)
    self.tick(5)
    self.assertEqual(self.send.call_count, 2)
    self.tick(4)
    self.tick(5)
    self.assertEqual(self.send.call_count, 2)
    self.tick(5, seconds=3600)
    self.assertEqual(self.send.call_count, 3)
    self.tick(-3)
    self.assertEqual(self.send.call_count, 4)
    self.assertIn("模拟盘", self.send.call_args.args[1])
    self.assertIn("-3", self.send.call_args.args[2])
    self.assertEqual(self.store.read()["runtime"]["roi_pct"], -3)
    self.assertEqual(self.store.read()["revision"], 1)

  def test_failure_is_redacted_retried_and_does_not_latch_success(self):
    self.save()
    self.send.side_effect = RuntimeError(self.destination)
    self.tick(5)
    self.assertEqual(self.send.call_count, 1)
    result = self.client.get("/api/v1/bark-settings")
    self.assertNotIn(self.destination, result.text)
    self.assertEqual(result.json()["history"][0]["error"], "bark_delivery_failed")
    for _ in range(4):
      self.tick(5)
    self.assertEqual(self.send.call_count, 1)
    self.send.side_effect = None
    self.tick(5)
    self.assertEqual(self.send.call_count, 2)
    self.tick(5, seconds=7200)
    self.assertEqual(self.send.call_count, 2)

  def test_state_changes_are_not_sent_for_initial_sample_but_retry_and_cooldown_work(self):
    self.save(profit_enabled=False, loss_enabled=False, state_enabled=True)
    self.tick(state="stopped")
    self.send.assert_not_called()
    self.send.side_effect = RuntimeError("fixture network failure")
    self.tick(state="running")
    self.assertEqual(self.send.call_count, 1)
    self.send.side_effect = None
    self.tick(seconds=300)
    self.assertEqual(self.send.call_count, 2)
    self.tick(state="paused")
    self.assertEqual(self.send.call_count, 2)
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 3)
    self.assertIn("paused", self.send.call_args.args[2])
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 3)

  def test_disabled_uninitialized_and_bad_metrics_do_not_send(self):
    self.monitor.tick()
    self.send.assert_not_called()
    self.assertFalse(self.store.path.exists())
    self.save()
    self.monitor.sample = lambda: None
    self.monitor.tick()
    self.assertEqual(self.store.read()["runtime"]["error"], "bark_bot_not_ready")
    self.monitor.sample = Mock(side_effect=RuntimeError(self.destination))
    self.monitor.tick()
    self.assertEqual(self.store.read()["runtime"]["error"], "bark_metrics_unavailable")
    self.monitor.sample = lambda: {"roi_pct": float("nan"), "bot_state": "running"}
    self.monitor.tick()
    self.send.assert_not_called()

  def test_unchanged_saves_do_not_rearm_but_changed_thresholds_do(self):
    self.save()
    self.tick(5)
    self.assertEqual(self.send.call_count, 1)
    self.save(revision=1, destination="", cooldown_minutes=30)
    self.tick(5, seconds=3600)
    self.assertEqual(self.send.call_count, 1)
    self.save(revision=2, destination="", profit_threshold_pct=4)
    self.tick(5)
    self.assertEqual(self.send.call_count, 2)
    self.save(revision=3, destination="", enabled=False)
    self.assertEqual(len(self.store.read()["runtime"]["history"]), 2)
    self.tick(5)
    self.assertEqual(self.send.call_count, 2)

  def test_atomic_storage_failure_corruption_and_symlink_fail_closed(self):
    self.save()
    with patch("nfi_account.bark.os.replace", side_effect=OSError("fixture disk failure")):
      self.assertEqual(self.save(revision=1, enabled=False).status_code, 503)
    self.assertTrue(self.store.read()["settings"]["enabled"])
    self.assertEqual(list(self.directory.glob(".nfi-bark-*")), [])
    original = self.store.path.read_text()
    for bad in ("[]", "{invalid", '{"schema_version": 1}'):
      self.store.path.write_text(bad)
      self.assertEqual(self.client.get("/api/v1/bark-settings").status_code, 503)
      self.monitor.tick()
    self.store.path.unlink()
    target = self.directory / "target.json"
    target.write_text(original)
    self.store.path.symlink_to(target)
    self.assertEqual(self.client.get("/api/v1/bark-settings").status_code, 503)
    self.monitor.tick()
    self.send.assert_not_called()

  def test_monitor_runs_without_browser_and_preserves_original_lifespan(self):
    events = []
    checked = threading.Event()

    @asynccontextmanager
    async def previous(app):
      events.append("start")
      yield
      events.append("stop")

    app, client = self.make_app(lifespan=previous)
    app.state.bark_monitor.tick = checked.set
    with client:
      self.assertTrue(checked.wait(3))
    self.assertEqual(events, ["start", "stop"])

  def test_stale_snapshot_cannot_send_after_admin_disables_notifications(self):
    self.save()

    def sample():
      self.store.save(SaveBark(enabled=False, revision=1, current_password=self.password))
      return {"roi_pct": 50, "bot_state": "running"}

    self.monitor.sample = sample
    self.monitor.tick()
    self.send.assert_not_called()


class BarkSenderTests(unittest.TestCase):
  def test_payload_uses_post_body_key_custom_prefix_no_redirects_and_checks_bark_ack(self):
    captured = []

    def handler(request):
      captured.append(request)
      return httpx.Response(200, json={"code": 200, "message": "success"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client(**kwargs):
      self.assertFalse(kwargs["trust_env"])
      self.assertFalse(kwargs["follow_redirects"])
      return real_client(transport=transport, **kwargs)

    with patch("nfi_account.bark.httpx.Client", side_effect=client):
      send_bark("https://bark.fixture.test/prefix/private-key", "收益达标", "测试消息", "paper")
    self.assertEqual(str(captured[0].url), "https://bark.fixture.test/prefix/push")
    self.assertEqual(captured[0].method, "POST")
    self.assertEqual(json.loads(captured[0].content)["device_key"], "private-key")
    for status, response in ((200, {"code": 400}), (302, {}), (500, {})):
      with patch("nfi_account.bark.httpx.Client") as mocked:
        mocked.return_value.__enter__.return_value.post.return_value = httpx.Response(status, json=response)
        with self.assertRaisesRegex(AccountError, "^bark_delivery_failed$"):
          send_bark("https://bark.fixture.test/private-key", "test", "body", "live")
    self.assertEqual(destination_parts("http://127.0.0.1:8080/key"), ("http://127.0.0.1:8080/push", "key"))

  def test_profit_snapshot_includes_partial_exit_and_fees_uses_starting_capital(self):
    from datetime import UTC, datetime

    from freqtrade.persistence import Order, Trade, init_db
    from freqtrade.rpc.rpc import RPC

    init_db("sqlite://")
    self.addCleanup(Trade.session.remove)
    now = datetime.now(UTC)
    # A reduced open position has realized profit; its remaining amount loses money.
    trade = Trade(
      pair="BTC/USDT",
      exchange="okx",
      is_open=True,
      is_short=False,
      amount=1,
      open_rate=100,
      stake_amount=100,
      max_stake_amount=200,
      fee_open=0.001,
      fee_close=0.001,
      open_date=now,
      realized_profit=100,
      leverage=1,
    )
    trade.recalc_open_trade_value()
    trade.orders = [
      Order(
        ft_order_side="buy",
        ft_pair="BTC/USDT",
        ft_amount=2,
        ft_price=100,
        ft_is_open=False,
        order_id="fixture-buy",
        status="closed",
        side="buy",
        filled=2,
        price=100,
        order_filled_date=now,
      ),
      Order(
        ft_order_side="sell",
        ft_pair="BTC/USDT",
        ft_amount=1,
        ft_price=200,
        ft_is_open=False,
        order_id="fixture-partial-sell",
        status="closed",
        side="sell",
        filled=1,
        price=200,
        order_filled_date=now,
      ),
    ]
    # The known partial fill realizes 200 * (1 - .001) - 100 * (1 + .001).
    trade.realized_profit = 99.7
    closed = Trade(
      pair="ETH/USDT",
      exchange="okx",
      is_open=False,
      is_short=False,
      amount=1,
      open_rate=100,
      stake_amount=100,
      fee_open=0.001,
      fee_close=0.001,
      open_date=now,
      close_date=now,
      close_profit_abs=450,
      close_profit=4.5,
    )
    Trade.session.add_all([trade, closed])
    Trade.commit()
    bot = Mock()
    bot.config = {"stake_currency": "USDT"}
    bot.state = "stopped"
    bot.wallets.get_starting_balance.return_value = 10000
    bot.exchange.get_rate.return_value = 90
    rpc = RPC(bot)
    with patch("freqtrade.rpc.api_server.deps.get_rpc_optional", return_value=rpc):
      result = profit_snapshot()
      # Closed 450 + partial realized 99.70 + remaining net loss -10.19 = 539.51 USDT.
      self.assertAlmostEqual(result["roi_pct"], 5.3951)
      self.assertEqual(result["bot_state"], "stopped")
      bot.exchange.create_order.assert_not_called()
      bot.wallets.update.assert_not_called()
      bot.exchange.get_rate.return_value = float("nan")
      with self.assertRaises(ValueError):
        profit_snapshot()
