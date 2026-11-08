import base64
import json
import tempfile
import unittest
from pathlib import Path
from typing import Annotated
from unittest.mock import patch

from fastapi import Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config
from nfi_account import configure_account_api


class AccountTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.old = "Initial-paper-pass-123"
    self.new = "Changed-paper-pass-456"
    self.app, self.manager, self.client = self.make_app()
    self.tokens = self.login(self.old).json()
    self.headers = {"Authorization": "Bearer " + self.tokens["access_token"]}

  def make_app(self):
    config = {
      "user_data_dir": self.directory.name,
      "api_server": {
        "username": "paper",
        "password": self.old,
        "jwt_secret_key": "initial-key-for-isolated-account-tests-only",
        "ws_token": "shared-data-consumer-key",
      },
    }
    app = FastAPI()
    app.dependency_overrides[get_api_config] = lambda: config["api_server"]
    manager = configure_account_api(app, config)
    app.include_router(api_auth.router_login, prefix="/api/v1")

    @app.get("/api/v1/protected", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])
    def protected():
      return {"ok": True}

    @app.websocket("/api/v1/message/ws")
    async def websocket(ws: WebSocket, user: Annotated[str | None, Depends(api_auth.validate_ws_token)]):
      if user is None:
        return
      await ws.accept()
      try:
        while True:
          await ws.send_text(await ws.receive_text())
      except WebSocketDisconnect:
        pass

    return app, manager, TestClient(app)

  def login(self, password, client=None):
    encoded = base64.b64encode(("paper:" + password).encode()).decode()
    return (client or self.client).post("/api/v1/token/login", headers={"Authorization": "Basic " + encoded})

  def change(self, current=None, new=None):
    return self.client.post(
      "/api/v1/account/password",
      headers=self.headers,
      json={
        "current_password": self.old if current is None else current,
        "new_password": self.new if new is None else new,
      },
    )

  def test_profile_requires_authentication_and_never_returns_secrets(self):
    self.assertEqual(self.client.get("/api/v1/account").status_code, 401)
    response = self.client.get("/api/v1/account", headers=self.headers)
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["username"], "paper")
    self.assertNotIn(self.old, response.text)
    self.assertNotIn(self.manager.generation, response.text)
    self.assertIsNone(response.json()["password_changed_at"])

  def test_password_change_invalidates_access_refresh_and_basic_logins(self):
    self.assertEqual(self.change().status_code, 200)
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.headers).status_code, 401)
    refresh = {"Authorization": "Bearer " + self.tokens["refresh_token"]}
    self.assertEqual(self.client.post("/api/v1/token/refresh", headers=refresh).status_code, 401)
    self.assertEqual(self.login(self.old).status_code, 401)
    self.assertEqual(self.login(self.new).status_code, 200)
    self.assertFalse(api_auth.verify_auth(self.manager.api_config, "paper", self.old))
    self.assertTrue(api_auth.verify_auth(self.manager.api_config, "paper", self.new))

  def test_credentials_survive_restart_with_only_a_private_hash_on_disk(self):
    self.assertEqual(self.change().status_code, 200)
    content = self.manager.path.read_text()
    self.assertNotIn(self.old, content)
    self.assertNotIn(self.new, content)
    self.assertEqual(self.manager.path.stat().st_mode & 0o777, 0o600)
    _, _, restarted = self.make_app()
    self.assertEqual(self.login(self.new, restarted).status_code, 200)
    self.assertEqual(self.login(self.old, restarted).status_code, 401)
    self.assertEqual(restarted.get("/api/v1/protected", headers=self.headers).status_code, 401)

  def test_wrong_current_password_does_not_change_credentials_or_sessions(self):
    response = self.change(current="incorrect")
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"], "account_incorrect_password")
    self.assertFalse(self.manager.path.exists())
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.headers).status_code, 200)

  def test_password_policy_and_request_validation_do_not_echo_secrets(self):
    for new in ["short", "x" * 129, "contains\na-newline", self.old]:
      with self.subTest(length=len(new)):
        response = self.change(new=new)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(new, response.text)
    response = self.client.post(
      "/api/v1/account/password", headers=self.headers, json={"new_password": self.new, "extra": self.old}
    )
    self.assertEqual(response.status_code, 400)
    self.assertNotIn(self.new, response.text)
    self.assertNotIn(self.old, response.text)

  def test_unicode_password_can_log_in_using_utf8_basic(self):
    password = "中文测试密码-Strong-2026!"
    self.assertEqual(self.change(new=password).status_code, 200)
    self.assertEqual(self.login(password).status_code, 200)
    encoded = base64.b64encode(("paper:" + password).encode()).decode()
    self.assertEqual(
      self.client.get("/api/v1/protected", headers={"Authorization": "Basic " + encoded}).status_code, 200
    )

  def test_logout_all_revokes_tokens_but_preserves_the_password(self):
    response = self.client.post(
      "/api/v1/account/sessions/revoke", headers=self.headers, json={"current_password": self.old}
    )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.headers).status_code, 401)
    self.assertEqual(self.login(self.old).status_code, 200)
    self.assertIsNone(json.loads(self.manager.path.read_text())["password_changed_at"])

  def test_storage_failure_keeps_the_existing_login_and_removes_temporary_files(self):
    with patch("nfi_account.credentials.os.replace", side_effect=OSError("test read-only storage")):
      response = self.change()
    self.assertEqual(response.status_code, 503)
    self.assertEqual(response.json()["detail"], "account_storage_unavailable")
    self.assertEqual(self.login(self.old).status_code, 200)
    self.assertEqual(self.client.get("/api/v1/protected", headers=self.headers).status_code, 200)
    self.assertFalse(self.manager.path.exists())
    self.assertEqual(list(Path(self.directory.name).glob(".nfi-account-*.tmp")), [])

  def test_repeated_incorrect_passwords_are_limited(self):
    for _ in range(4):
      self.assertEqual(self.change(current="incorrect").status_code, 400)
    self.assertEqual(self.change(current="incorrect").status_code, 429)
    self.assertEqual(self.change().status_code, 429)
    self.assertEqual(self.login(self.old).status_code, 429)

  def test_corrupted_credentials_fail_closed(self):
    self.manager.path.write_text('{"password_hash":"invalid"}')
    with self.assertRaisesRegex(RuntimeError, "Invalid NFI account"):
      self.make_app()

  def test_websocket_logins_close_when_sessions_are_revoked(self):
    with self.client.websocket_connect("/api/v1/message/ws?token=" + self.tokens["access_token"]) as ws:
      ws.send_text("ping")
      self.assertEqual(ws.receive_text(), "ping")
      self.assertEqual(self.change().status_code, 200)
      with self.assertRaises(WebSocketDisconnect) as error:
        ws.receive_text()
      self.assertEqual(error.exception.code, 1008)

  def test_shared_websocket_consumers_are_preserved(self):
    with self.client.websocket_connect("/api/v1/message/ws?token=shared-data-consumer-key") as ws:
      self.assertEqual(self.change().status_code, 200)
      ws.send_text("still connected")
      self.assertEqual(ws.receive_text(), "still connected")


if __name__ == "__main__":
  unittest.main()
