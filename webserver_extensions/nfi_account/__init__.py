"""Account API integration for the pinned Freqtrade image."""

import base64
import binascii
import secrets
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, SecretStr
from starlette.concurrency import run_in_threadpool
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config

from .credentials import AccountError, AccountManager, MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH
from .attempts import MAX_FAILURES, WINDOW_SECONDS, FREEZE_SECONDS

_managers = {}
_original_verify = api_auth.verify_auth
_original_login = api_auth.token_login
_original_refresh = api_auth.token_refresh
_installed = False


def unauthorized():
  return HTTPException(401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


def managed_verify(api_config, username, password):
  manager = _managers.get(id(api_config))
  return manager.authenticate(username, password) if manager else _original_verify(api_config, username, password)


async def utf8_basic(request: Request, api_config: Annotated[dict, Depends(get_api_config)]):
  try:
    authorization = request.headers.get("authorization", "")
    if len(authorization) > 8192:
      raise ValueError()
    scheme, encoded = authorization.split(" ", 1)
    if scheme.lower() != "basic":
      raise ValueError()
    username, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
    return HTTPBasicCredentials(username=username, password=password)
  except (ValueError, UnicodeError, binascii.Error):
    manager = _managers.get(id(api_config))
    if manager:
      await run_in_threadpool(manager.attempts.verify, "password", lambda: False)
    raise HTTPException(401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"}) from None


async def utf8_optional_basic(request: Request, api_config: Annotated[dict, Depends(get_api_config)]):
  if not request.headers.get("authorization", "").lower().startswith("basic "):
    return None
  return await utf8_basic(request, api_config)


def account_manager(api_config: Annotated[dict, Depends(get_api_config)]):
  manager = _managers.get(id(api_config))
  if manager is None:
    raise HTTPException(503, detail="account_unavailable")
  return manager


def token_login(
  form_data: Annotated[HTTPBasicCredentials, Depends(utf8_basic)], api_config: Annotated[dict, Depends(get_api_config)]
):
  manager = _managers.get(id(api_config))
  if manager is None:
    return _original_login(form_data, api_config)
  # Password verification and token issuance must use the same credential generation.
  with manager.lock:
    if not manager.authenticate(form_data.username, form_data.password):
      raise unauthorized()
    data = {"identity": {"u": form_data.username}}
    secret = manager.generation
    return {
      "access_token": api_auth.create_token(data, secret),
      "refresh_token": api_auth.create_token(data, secret, "refresh"),
    }


def token_refresh(
  token: Annotated[str, Depends(api_auth.oauth2_scheme)], api_config: Annotated[dict, Depends(get_api_config)]
):
  manager = _managers.get(id(api_config))
  if manager is None:
    return _original_refresh(token, api_config)
  with manager.lock:
    username = api_auth.get_user_from_token(token, manager.generation, "refresh")
    if username != api_config["username"]:
      raise unauthorized()
    return {"access_token": api_auth.create_token({"identity": {"u": username}}, manager.generation)}


class SecretRoute(APIRoute):
  def get_route_handler(self):
    original = super().get_route_handler()

    async def handler(request):
      try:
        return await original(request)
      except RequestValidationError:
        # FastAPI's default validation body can echo submitted secrets.
        raise HTTPException(400, detail="account_invalid_request") from None

    return handler


class CurrentPassword(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  current_password: SecretStr


class ChangePassword(CurrentPassword):
  new_password: SecretStr


router = APIRouter(
  prefix="/api/v1/account",
  tags=["Account"],
  route_class=SecretRoute,
  dependencies=[Depends(api_auth.http_basic_or_jwt_token)],
)


@router.get("")
def profile(manager: Annotated[AccountManager, Depends(account_manager)]):
  with manager.lock:
    return {
      "username": manager.api_config["username"],
      "password_changed_at": manager.state["password_changed_at"] if manager.state else None,
      "sessions_revoked_at": manager.state["sessions_revoked_at"] if manager.state else None,
      "min_password_length": MIN_PASSWORD_LENGTH,
      "max_password_length": MAX_PASSWORD_LENGTH,
      "access_token_minutes": 15,
      "refresh_token_days": 30,
      "password_protection": {
        "max_failures": MAX_FAILURES,
        "window_seconds": WINDOW_SECONDS,
        "freeze_seconds": FREEZE_SECONDS,
        "retry_after": manager.attempts.remaining(),
      },
    }


async def apply_change(manager, action, *args):
  await run_in_threadpool(action, *args)
  await manager.close_browser_sessions()
  return {"success": True, "reauthenticate": True}


@router.post("/password")
async def change_password(body: ChangePassword, manager: Annotated[AccountManager, Depends(account_manager)]):
  return await apply_change(
    manager, manager.change_password, body.current_password.get_secret_value(), body.new_password.get_secret_value()
  )


@router.post("/sessions/revoke")
async def revoke_sessions(body: CurrentPassword, manager: Annotated[AccountManager, Depends(account_manager)]):
  return await apply_change(manager, manager.revoke_sessions, body.current_password.get_secret_value())


class AccountSessionMiddleware:
  def __init__(self, app, manager):
    self.app = app
    self.manager = manager

  async def __call__(self, scope, receive, send):
    if scope["type"] != "websocket" or scope["path"] != "/api/v1/message/ws":
      return await self.app(scope, receive, send)
    # Shared websocket keys belong to data consumers, not interactive account logins.
    token = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="replace")).get("token", [""])[0]
    shared = self.manager.api_config.get("ws_token") or []
    if isinstance(shared, str):
      shared = [shared]
    if token and any(secrets.compare_digest(token.encode(), value.encode()) for value in shared):
      return await self.app(scope, receive, send)
    generation = self.manager.generation

    async def tracked_send(message):
      if message["type"] == "websocket.accept":
        if generation != self.manager.generation:
          await send({"type": "websocket.close", "code": 1008})
          return
        self.manager.websockets.add(send)
      await send(message)

    try:
      await self.app(scope, receive, tracked_send)
    finally:
      self.manager.websockets.discard(send)


async def account_error_response(_request, exc):
  body = {"detail": exc.code}
  headers = {}
  if exc.retry_after is not None:
    body["retry_after"] = exc.retry_after
    headers["Retry-After"] = str(exc.retry_after)
  return JSONResponse(status_code=exc.status, content=body, headers=headers)


def configure_account_api(app, config):
  global _installed
  manager = AccountManager(config)
  _managers[id(config["api_server"])] = manager
  if not _installed:
    api_auth.verify_auth = managed_verify
    # Keep the upstream router object used by ApiServer, replacing only token routes.
    api_auth.router_login.routes[:] = [
      r for r in api_auth.router_login.routes if r.path not in ("/token/login", "/token/refresh")
    ]
    api_auth.router_login.add_api_route("/token/login", token_login, methods=["POST"])
    api_auth.router_login.add_api_route("/token/refresh", token_refresh, methods=["POST"])
    _installed = True
  app.dependency_overrides.setdefault(api_auth.httpbasic, utf8_optional_basic)
  app.include_router(router)
  app.add_exception_handler(AccountError, account_error_response)
  app.add_middleware(AccountSessionMiddleware, manager=manager)
  from .startup import configure_startup_api

  configure_startup_api(app, config)
  from .bark import configure_bark_api

  configure_bark_api(app, config)
  return manager
