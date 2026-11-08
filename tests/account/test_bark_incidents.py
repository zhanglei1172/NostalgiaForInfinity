import json
import unittest
from unittest.mock import patch

import test_bark
from nfi_account.bark import BarkMonitor
from nfi_account.faults import FaultJournal


class BarkIncidentTests(unittest.TestCase):
  setUp = test_bark.BarkTests.setUp
  save = test_bark.BarkTests.save
  tick = test_bark.BarkTests.tick
  make_app = test_bark.BarkTests.make_app

  def enable(self, **changes):
    self.journal = FaultJournal(now=lambda: self.clock)
    self.monitor.operations = self.journal.snapshot
    with patch("nfi_account.bark.time.time", side_effect=lambda: self.clock):
      result = self.save(
        profit_enabled=False,
        loss_enabled=False,
        trade_error_enabled=True,
        exchange_error_enabled=True,
        recovery_enabled=True,
        **changes,
      )
    self.assertEqual(result.status_code, 200, result.text)

  def test_order_failure_notifies_once_and_new_failures_group_within_the_cooldown(self):
    self.enable()
    self.journal.record("create_order", "BTC/USDT", code="insufficient_funds", trade=True)
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    self.assertIn("余额不足", self.send.call_args.args[2])
    self.assertIn("BTC/USDT", self.send.call_args.args[2])
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    for _ in range(3):
      self.journal.record("cancel_order", "ETH/USDT", code="order_rejected", trade=True)
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 2)
    self.assertIn("3 次", self.send.call_args.args[2])

  def test_short_connection_failure_does_not_alert_or_send_a_false_recovery(self):
    self.enable()
    self.journal.record("get_balances", code="connection")
    self.tick(seconds=60)
    self.journal.record("get_balances")
    self.tick(seconds=60)
    self.send.assert_not_called()

  def test_persistent_fault_and_recovery_are_deduplicated_across_monitor_restart(self):
    self.enable()
    self.journal.record("fetch_ticker", "BTC/USDT", code="rate_limited")
    self.tick(seconds=120)
    self.assertEqual(self.send.call_count, 1)
    self.assertIn("限流", self.send.call_args.args[2])
    self.monitor = BarkMonitor(self.store, "paper", lambda: self.value, self.send, lambda: self.clock)
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 1)
    self.monitor.operations = self.journal.snapshot
    self.journal.record("fetch_ticker", "ETH/USDT")
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    self.journal.record("fetch_ticker", "BTC/USDT")
    self.tick()
    self.assertEqual(self.send.call_count, 2)
    self.assertIn("连接恢复", self.send.call_args.args[1])
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 2)

  def test_error_alerts_work_even_when_profit_metrics_are_unavailable(self):
    self.enable()
    self.monitor.sample = lambda: None
    self.journal.record("get_balances", code="authentication")
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    self.assertIn("权限", self.send.call_args.args[2])
    result = self.client.get("/api/v1/bark-settings").json()
    self.assertEqual(result["monitor_error"], "bark_bot_not_ready")
    self.assertEqual(result["active_incidents"][0]["code"], "authentication")

  def test_failed_error_delivery_retries_and_recovery_requires_an_accepted_alert(self):
    self.enable()
    self.journal.record("create_order", "ETH/USDT", code="order_uncertain", trade=True)
    self.send.side_effect = RuntimeError(self.destination)
    self.tick()
    self.assertEqual(self.send.call_count, 1)
    self.tick(seconds=240)
    self.assertEqual(self.send.call_count, 1)
    self.send.side_effect = None
    self.tick(seconds=60)
    self.assertEqual(self.send.call_count, 2)
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 2)
    self.assertEqual(self.store.read()["runtime"]["operational"]["trades"], [])

  def test_old_settings_migrate_with_error_events_off_without_losing_the_destination_or_history(self):
    self.assertEqual(self.save().status_code, 200)
    self.tick(5)
    data = json.loads(self.store.path.read_text())
    for field in ("trade_error_enabled", "exchange_error_enabled", "recovery_enabled", "exchange_grace_minutes"):
      data["settings"].pop(field)
    data["runtime"].pop("operational")
    self.store.path.write_text(json.dumps(data))
    migrated = self.store.read()
    self.assertEqual(migrated["destination"], self.destination)
    self.assertEqual(len(migrated["runtime"]["history"]), 1)
    self.assertFalse(migrated["settings"]["trade_error_enabled"])
    self.assertFalse(migrated["settings"]["exchange_error_enabled"])

  def test_cooldown_state_and_public_context_never_contain_provider_errors(self):
    self.enable()
    self.journal.record("create_order", "BTC/USDT", code="order_rejected", trade=True)
    self.tick()
    result = self.client.get("/api/v1/bark-settings")
    self.assertEqual(result.json()["history"][0]["context"]["pair"], "BTC/USDT")
    self.assertNotIn("fixture-private-device", result.text)
    data = self.store.read()
    data["runtime"]["history"][0]["context"]["raw_error"] = "fixture-secret"
    self.store.path.write_text(json.dumps(data))
    rejected = self.client.get("/api/v1/bark-settings")
    self.assertEqual(rejected.status_code, 503)
    self.assertNotIn("fixture-secret", rejected.text)

  def test_connection_recovery_is_not_sent_after_an_unaccepted_fault_alert(self):
    self.enable()
    self.send.side_effect = RuntimeError("fixture failure")
    self.journal.record("get_balances", code="connection")
    self.tick(seconds=120)
    self.assertEqual(self.send.call_count, 1)
    self.send.side_effect = None
    self.journal.record("get_balances")
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 1)

  def test_incident_sampling_errors_never_claim_that_the_exchange_recovered(self):
    self.enable()
    self.journal.record("get_balances", code="authentication")
    self.tick()
    self.monitor.operations = lambda: (_ for _ in ()).throw(ValueError("fixture-secret"))
    self.tick(seconds=3600)
    self.assertEqual(self.send.call_count, 1)
    self.assertEqual(self.store.read()["runtime"]["error"], "bark_health_unavailable")
