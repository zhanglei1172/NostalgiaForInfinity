import io
import json
import logging
import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from freqtrade.enums import State
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api
from nfi_account.credentials import AccountError
from nfi_account.proxy import (
  ProxyStore,
  configure_account_client,
  configure_client,
  defaults,
  install_redaction,
  prepare_proxy,
  proxy_url,
  validate_settings,
)
from nfi_account.proxy_api import probe_connection
from nfi_live.storage import LiveStore


class ProxyTests(unittest.TestCase):
  def setUp(self):
    self.temporary = tempfile.TemporaryDirectory()
    self.addCleanup(self.temporary.cleanup)
    self.directory = Path(self.temporary.name)
    self.store = ProxyStore(self.directory)
    self.settings = {
      **defaults(),
      "enabled": True,
      "host": "proxy.example.test",
      "auth_enabled": True,
      "username": "fixture-proxy-user",
      "password": "fixture:p@ss/word",
    }
    self.password = "fixture-proxy-admin-password"
    self.config = {
      "user_data_dir": self.directory,
      "dry_run": False,
      "runmode": "live",
      "api_server": {"username": "live", "password": self.password, "jwt_secret_key": "fixture-key"},
    }
    self.app = FastAPI()
    self.app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"}):
      self.manager = configure_account_api(self.app, self.config)
    self.client = TestClient(self.app)
    self.client.auth = ("live", self.password)
    self.rpc = SimpleNamespace(_freqtrade=SimpleNamespace(state=State.STOPPED))
    self.rpc_patch = patch("nfi_account.proxy_api.get_rpc_optional", return_value=self.rpc).start()
    self.addCleanup(patch.stopall)

  def body(self, **changes):
    return {**self.settings, "revision": 0, "current_password": self.password, **changes}

  def save(self, **changes):
    return self.client.put("/api/v1/proxy-settings", json=self.body(**changes))

  def activate(self):
    data = self.store.read()
    data.update(active=deepcopy(data["draft"]), active_revision=data["revision"])
    with self.store.exclusive():
      self.store.write(data)

  def test_default_direct_and_independent_private_drafts_never_modify_live_account(self):
    self.assertFalse(self.client.get("/api/v1/proxy-settings").json()["settings"]["enabled"])
    self.assertFalse(self.store.path.exists())
    self.rpc._freqtrade.state = State.RUNNING
    response = self.save()
    self.assertEqual(response.status_code, 200, response.text)
    self.assertTrue(response.json()["pending_changes"])
    self.assertFalse(response.json()["active_enabled"])
    self.assertEqual(self.rpc._freqtrade.state, State.RUNNING)
    self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
    self.assertFalse((self.directory / "live-profile.json").exists())
    self.assertFalse(ProxyStore(self.directory / "paper").read()["draft"]["enabled"])
    self.assertFalse(ProxyStore(self.directory).read()["active"]["enabled"])
    for secret in (self.settings["username"], self.settings["password"], self.password):
      self.assertNotIn(secret, response.text)

  def test_blank_credentials_preserve_saved_values_and_disabling_auth_clears_them(self):
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save(revision=1, username="", password="", host="other.example.test").status_code, 200)
    self.assertEqual(self.store.read()["draft"]["password"], self.settings["password"])
    self.assertEqual(self.save(revision=2, auth_enabled=False, username="", password="").status_code, 200)
    self.assertEqual(self.store.read()["draft"]["username"], "")
    self.assertEqual(self.store.read()["draft"]["password"], "")
    self.assertFalse(self.client.get("/api/v1/proxy-settings").json()["settings"]["password_configured"])

  def test_invalid_input_revision_conflicts_and_storage_failures_do_not_echo_secrets(self):
    for change in (
      {"host": "https://proxy.test"},
      {"host": "proxy.test/path"},
      {"port": 0},
      {"port": "fixture-secret"},
      {"host": "a\n.test"},
      {"protocol": "file"},
      {"username": "", "password": ""},
      {"extra": "fixture-secret"},
    ):
      response = self.save(**change)
      self.assertEqual(response.status_code, 400, change)
      self.assertNotIn("fixture-secret", response.text)
      self.assertNotIn(self.settings["password"], response.text)
    self.assertEqual(self.save().status_code, 200)
    self.assertEqual(self.save().status_code, 409)
    before = self.store.path.read_bytes()
    with patch("nfi_account.proxy.os.replace", side_effect=OSError("fixture-private-storage")):
      response = self.save(revision=1)
    self.assertEqual(response.status_code, 503)
    self.assertNotIn("fixture-private-storage", response.text)
    self.assertEqual(self.store.path.read_bytes(), before)
    self.assertEqual(list(self.directory.glob(".proxy-*")), [])

  def test_authenticated_same_origin_and_shared_password_freeze_protect_all_operations(self):
    self.client.auth = None
    self.assertEqual(self.client.get("/api/v1/proxy-settings").status_code, 401)
    self.client.auth = ("live", self.password)
    response = self.client.put("/api/v1/proxy-settings", json=self.body(), headers={"Origin": "https://evil.test"})
    self.assertEqual(response.status_code, 403)
    from freqtrade.rpc.api_server.api_auth import create_token

    self.client.auth = None
    self.client.headers["Authorization"] = "Bearer " + create_token(
      {"identity": {"u": "live"}}, self.manager.generation
    )
    for _ in range(4):
      self.assertEqual(self.save(current_password="wrong").status_code, 400)
    response = self.client.post("/api/v1/proxy-settings/check", json=self.body(current_password="wrong"))
    self.assertEqual(response.status_code, 429)
    self.assertEqual(response.headers["Retry-After"], "300")
    self.assertEqual(self.save().status_code, 429)
    self.assertFalse(self.store.path.exists())

  def test_reverse_proxy_save_and_application_are_explicit_and_leave_bot_stopped(self):
    self.client.headers.update({"Origin": "https://console.example.test", "Sec-Fetch-Site": "same-origin"})
    self.assertEqual(self.save().status_code, 200)
    self.rpc._freqtrade.state = State.RUNNING
    body = {"revision": 1, "current_password": self.password}
    self.assertEqual(self.client.post("/api/v1/proxy-settings/apply", json=body).status_code, 409)
    self.rpc._freqtrade.state = State.PAUSED
    self.assertEqual(self.client.post("/api/v1/proxy-settings/apply", json=body).status_code, 409)
    self.rpc._freqtrade.state = State.STOPPED
    live = LiveStore(self.directory)
    with patch.object(LiveStore, "database_counts", return_value={"open_trades": 1, "open_orders": 0, "trades": 1}):
      self.assertEqual(self.client.post("/api/v1/proxy-settings/apply", json=body).status_code, 409)
    with patch.object(LiveStore, "profile", return_value={"nfi_live_revision": 4}):
      response = self.client.post("/api/v1/proxy-settings/apply", json=body)
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual(self.store.read()["active"], self.settings)
    self.assertEqual(self.store.read()["active_revision"], 1)
    self.assertEqual(self.rpc._freqtrade.state, State.STOPPED)
    self.assertIsNotNone(live.reload_nonce())
    self.assertEqual(live.status()["phase"], "applying")

  def test_test_uses_only_draft_does_not_apply_and_is_rate_limited(self):
    self.rpc._freqtrade.state = State.RUNNING
    result = {
      "success": True,
      "checks": {"rest_sync": {"success": True}, "rest_async": {"success": True}, "websocket": {"success": True}},
      "checked_at": "fixture-time",
    }
    with patch("nfi_account.proxy_api.probe_connection", return_value=result) as probe:
      response = self.client.post("/api/v1/proxy-settings/check", json=self.body())
      self.assertEqual(response.status_code, 200)
      probe.assert_called_once_with(self.settings)
      self.assertFalse(self.store.read()["active"]["enabled"])
      self.assertFalse(self.store.read()["draft"]["enabled"])
      self.assertEqual(self.rpc._freqtrade.state, State.RUNNING)
      self.assertEqual(self.client.post("/api/v1/proxy-settings/check", json=self.body()).status_code, 429)

  def test_failed_live_worker_can_select_direct_without_connecting_to_the_broken_proxy(self):
    self.rpc_patch.return_value = None
    self.assertEqual(self.save().status_code, 200)
    self.activate()
    live = LiveStore(self.directory)
    live.write_status("error", 2, "live_start_failed")
    with patch.object(LiveStore, "profile", return_value={"nfi_live_revision": 2}):
      self.assertEqual(self.save(revision=1, enabled=False, username="", password="").status_code, 200)
      result = self.client.post(
        "/api/v1/proxy-settings/apply", json={"revision": 2, "current_password": self.password}
      )
    self.assertEqual(result.status_code, 200, result.text)
    self.assertFalse(self.store.read()["active"]["enabled"])
    self.assertIsNotNone(live.reload_nonce())
    self.assertEqual(live.status()["phase"], "applying")

  def test_paper_reload_blocks_start_until_the_saved_transport_is_loaded(self):
    self.config.update(dry_run=True, runmode="dry_run", nfi_proxy_revision=0)
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: self.config["api_server"]
    with patch.dict(os.environ, {"NFI_RECIPE_ROLE": "paper"}):
      configure_account_api(app, self.config)
    client = TestClient(app)
    client.auth = ("live", self.password)
    with (
      patch("freqtrade.persistence.Trade.get_open_trade_count", return_value=0),
      patch("freqtrade.persistence.Order.get_open_orders", return_value=[]),
    ):
      self.assertEqual(client.put("/api/v1/proxy-settings", json=self.body()).status_code, 200)
      response = client.post("/api/v1/proxy-settings/apply", json={"revision": 1, "current_password": self.password})
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual(self.rpc._freqtrade.state, State.RELOAD_CONFIG)
    self.assertEqual(client.post("/api/v1/start").status_code, 409)
    self.config["nfi_proxy_revision"] = 1
    self.rpc._rpc_start = lambda: {"status": "starting"}
    self.assertEqual(client.post("/api/v1/start").status_code, 200)

  def test_sync_async_and_websocket_clients_receive_matching_transport_and_direct_clears_env(self):
    for protocol in ("socks5h", "socks5", "http", "https"):
      settings = {**self.settings, "protocol": protocol}
      for _kind in ("sync", "async", "ws"):
        client = SimpleNamespace(session=SimpleNamespace(trust_env=True))
        configure_client(client, settings)
        self.assertFalse(client.session.trust_env)
        self.assertFalse(client.aiohttp_trust_env)
        if protocol.startswith("socks"):
          self.assertEqual(client.socksProxy, proxy_url(settings))
          self.assertEqual(client.wsSocksProxy, proxy_url(settings))
          self.assertIsNone(client.httpsProxy)
        else:
          self.assertEqual(client.httpsProxy, proxy_url(settings))
          self.assertEqual(client.wssProxy, proxy_url(settings))
        configure_client(client, defaults())
        self.assertIsNone(client.socksProxy)
        self.assertIsNone(client.wssProxy)
        self.assertIsNone(client.proxies)

  def test_worker_and_account_checks_use_active_snapshot_and_never_draft_credentials(self):
    from freqtrade.exchange.exchange import Exchange

    self.store.save(self.settings, 0)
    client = SimpleNamespace()
    with (
      patch.dict(os.environ, {"NFI_RECIPE_ROLE": "live"}),
      patch.object(Exchange, "_init_ccxt", return_value=client),
    ):
      prepare_proxy(self.config)
      exchange = SimpleNamespace(_config=self.config)
      Exchange._init_ccxt(exchange, {}, True, {})
      self.assertFalse(hasattr(client, "socksProxy") and client.socksProxy)
      self.activate()
      prepare_proxy(self.config)
      Exchange._init_ccxt(exchange, {}, False, {})
      self.assertEqual(client.socksProxy, proxy_url(self.settings))
      self.assertEqual(self.config["nfi_proxy_revision"], 1)
      self.assertNotIn(self.settings["password"], json.dumps(self.config, default=str))
    other = configure_account_client(SimpleNamespace(), self.directory)
    self.assertEqual(other.socksProxy, proxy_url(self.settings))

  def test_invalid_private_storage_is_rejected_and_proxy_secrets_are_redacted_from_tracebacks(self):
    self.store.path.write_text('{"schema_version": 1}')
    self.assertEqual(self.client.get("/api/v1/proxy-settings").status_code, 503)
    self.store.path.unlink()
    target = self.directory / "outside.json"
    target.write_text("{}")
    self.store.path.symlink_to(target)
    with self.assertRaises(AccountError):
      self.store.read()
    install_redaction(self.settings)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("proxy-fixture")
    logger.addHandler(handler)
    try:
      try:
        raise ValueError(proxy_url(self.settings) + " " + self.settings["password"])
      except ValueError:
        logger.exception("Proxy request failed: %s", proxy_url(self.settings))
    finally:
      logger.removeHandler(handler)
    self.assertNotIn(self.settings["password"], stream.getvalue())
    self.assertNotIn(self.settings["username"], stream.getvalue())
    self.assertIn("[proxy-redacted]", stream.getvalue())

  def test_probe_errors_never_echo_proxy_urls_or_exchange_responses(self):
    import ccxt

    with (
      patch("nfi_account.proxy_api.ccxt.okx", side_effect=ccxt.NetworkError(proxy_url(self.settings))),
      patch("nfi_account.proxy_api.ccxt.pro.okx", side_effect=ValueError("fixture-private-response")),
    ):
      result = probe_connection(self.settings)
    self.assertFalse(result["success"])
    self.assertEqual(set(result["checks"]), {"rest_sync", "rest_async", "websocket"})
    self.assertNotIn(self.settings["password"], json.dumps(result))
    self.assertNotIn("fixture-private-response", json.dumps(result))

  def test_ipv6_idna_and_escaped_credentials_build_valid_urls(self):
    settings = validate_settings({**self.settings, "host": "[::1]"})
    self.assertEqual(settings["host"], "::1")
    self.assertIn("@[::1]:1080", proxy_url(settings))
    self.assertIn("fixture%3Ap%40ss%2Fword", proxy_url(settings))
    self.assertEqual(validate_settings({**self.settings, "host": "代理.example"})["host"], "xn--mnq481g.example")
