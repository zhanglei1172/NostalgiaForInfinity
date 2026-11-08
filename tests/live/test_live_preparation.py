import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import rapidjson
from nfi_research.recipe import DEFAULTS
from prepare_live import build_config, check_exchange, checked_config, main, write_files

CONFIGS = Path("/live-configs")
STRATEGY = Path("/live-strategy.py")


class LivePreparationTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.target = Path(self.directory.name)
    mode = rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS
    self.base = rapidjson.loads((CONFIGS / "exampleconfig.json").read_text(), parse_mode=mode)
    self.blacklist = rapidjson.loads((CONFIGS / "blacklist-okx.json").read_text(), parse_mode=mode)["exchange"][
      "pair_blacklist"
    ]
    self.document = {"schema_version": 1, "revision": 7, "settings": DEFAULTS}

  def config(self):
    return build_config(copy.deepcopy(self.base), self.blacklist, self.document, 1000)

  def write(self):
    write_files(
      self.target,
      STRATEGY,
      self.config(),
      "fixture-key",
      "fixture-secret",
      "fixture-web-password",
      "fixture-passphrase",
    )

  def test_prepared_live_settings_have_a_separate_capital_and_keep_the_strategy_requirements(self):
    config = self.config()
    self.assertEqual(config["exchange"]["name"], "okx")
    self.assertFalse(config["dry_run"])
    self.assertEqual(config["initial_state"], "stopped")
    self.assertEqual(config["available_capital"], 1000)
    self.assertEqual(config["timeframe"], "5m")
    self.assertTrue(config["use_exit_signal"])
    self.assertFalse(config["exit_profit_only"])
    self.assertTrue(config["ignore_roi_if_entry_signal"])
    self.assertEqual(config["nfi_recipe_revision"], 7)
    self.assertEqual(config["pairlists"][-1]["number_assets"], 40)
    for name in ("dry_run_wallet", "fee", "tradable_balance_ratio", "add_config_files", "original_config"):
      self.assertNotIn(name, config)

  def test_invalid_capital_is_rejected(self):
    for capital in (float("nan"), float("inf"), -1, 0, 99):
      with self.assertRaises(ValueError):
        build_config(copy.deepcopy(self.base), self.blacklist, self.document, capital)

  def test_credentials_are_private_and_the_strategy_is_a_snapshot(self):
    self.write()
    for name in ("config.json", "credentials.json"):
      self.assertEqual((self.target / name).stat().st_mode & 0o777, 0o600)
    config_text = (self.target / "config.json").read_text()
    self.assertNotIn("fixture-key", config_text)
    self.assertNotIn("fixture-secret", config_text)
    self.assertNotIn("fixture-web-password", config_text)
    self.assertEqual((self.target / "strategies/NostalgiaForInfinityX8.py").read_bytes(), STRATEGY.read_bytes())
    credentials = json.loads((self.target / "credentials.json").read_text())
    self.assertEqual(credentials["api_server"]["username"], "live-admin")
    self.assertEqual(len(credentials["api_server"]["jwt_secret_key"]), 64)
    self.assertEqual(credentials["exchange"]["password"], "fixture-passphrase")

  def test_preparation_refuses_to_overwrite_an_existing_live_directory(self):
    existing = self.target / "trades-live.sqlite"
    existing.write_bytes(b"existing-live-database")
    with self.assertRaises(ValueError):
      self.write()
    self.assertEqual(existing.read_bytes(), b"existing-live-database")
    self.assertEqual(list(self.target.iterdir()), [existing])

  def test_failed_preparation_rolls_back_its_files(self):
    with patch.object(Path, "write_bytes", side_effect=OSError("fixture disk failure")):
      with self.assertRaises(OSError):
        self.write()
    self.assertEqual(list(self.target.iterdir()), [])

  def test_real_freqtrade_config_and_frozen_strategy_validate_without_network_or_secret_output(self):
    self.write()
    output = io.StringIO()
    with (
      patch("prepare_live.LIVE_DIR", self.target),
      patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"}),
      patch("ccxt.okx", side_effect=AssertionError("Offline check attempted an exchange connection")),
      redirect_stdout(output),
    ):
      config = checked_config()
    self.assertFalse(config["dry_run"])
    self.assertIn('"initial_state": "stopped"', output.getvalue())
    for secret in ("fixture-key", "fixture-secret", "fixture-web-password", "fixture-passphrase"):
      self.assertNotIn(secret, output.getvalue())

  def test_exchange_check_reads_balance_only_and_enforces_the_initial_budget(self):
    client = MagicMock()
    client.fetch_balance.return_value = {"USDT": {"free": 1100}}
    config = self.config()
    config["exchange"].update(key="fixture-key", secret="fixture-secret", password="fixture-passphrase")
    with (
      patch("ccxt.okx", return_value=client) as factory,
      patch("ccxt.binance", side_effect=AssertionError("Wrong exchange")),
      redirect_stdout(io.StringIO()),
    ):
      check_exchange(config)
      self.assertEqual(factory.call_args[0][0]["password"], "fixture-passphrase")
      self.assertEqual([c[0] for c in client.mock_calls], ["fetch_balance"])
      client.fetch_balance.return_value = {"USDT": {"free": 900}}
      with self.assertRaises(ValueError):
        check_exchange(config)

  def test_cli_initialization_uses_the_active_recipe_and_never_prints_credentials(self):
    with tempfile.TemporaryDirectory() as source_name:
      source = Path(source_name)
      (source / "configs").mkdir()
      for name in ("exampleconfig.json", "blacklist-okx.json"):
        (source / "configs" / name).write_bytes((CONFIGS / name).read_bytes())
      (source / "recipes").mkdir()
      (source / "recipes/active.json").write_text(json.dumps(self.document))
      (source / "NostalgiaForInfinityX8.py").write_bytes(STRATEGY.read_bytes())
      output = io.StringIO()
      with (
        patch("prepare_live.SOURCE_DIR", source),
        patch("prepare_live.LIVE_DIR", self.target),
        patch("sys.argv", ["prepare_live.py", "--capital", "1000"]),
        patch(
          "getpass.getpass",
          side_effect=[
            "fixture-key",
            "fixture-secret",
            "fixture-passphrase",
            "fixture-web-password",
            "fixture-web-password",
          ],
        ),
        redirect_stdout(output),
      ):
        main()
      saved = json.loads((self.target / "config.json").read_text())
      self.assertEqual(saved["nfi_recipe_revision"], 7)
      self.assertEqual(saved["available_capital"], 1000)
      for secret in ("fixture-key", "fixture-secret", "fixture-web-password", "fixture-passphrase"):
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
  unittest.main()
