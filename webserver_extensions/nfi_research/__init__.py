"""Authenticated research gateway and a separate, non-trading research worker."""

import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from freqtrade.rpc.api_server import api_auth

from .activity import configure_activity_api
from .preparation import configure_worker
from .recipe import configure_recipe_api


def allowed(method: str, path: str) -> bool:
  reads = (
    r"(?:info|strategies|strategy/[A-Za-z0-9_]+|backtest(?:/abort|/history|/history/result)?"
    r"|backtest/history/[A-Za-z0-9_-]+/[A-Za-z0-9_]+/wallet)"
  )
  return (method == "GET" and re.fullmatch(reads, path) is not None) or (
    method == "POST" and path in ("prepare", "backtest")
  )


def configure_research_api(app, config):
  configure_activity_api(app, config)
  configure_recipe_api(app, config)
  if str(config.get("runmode")) == "webserver" and os.environ.get("NFI_RECIPE_ROLE") != "live":
    configure_worker(app, config)
  target = os.environ.get("NFI_RESEARCH_URL", "").rstrip("/")
  username = os.environ.get(
    "NFI_RESEARCH_USERNAME",
    os.environ.get("FREQTRADE__API_SERVER__USERNAME", config["api_server"].get("username", "")),
  )
  password = os.environ.get(
    "NFI_RESEARCH_PASSWORD",
    os.environ.get("FREQTRADE__API_SERVER__PASSWORD", config["api_server"].get("password", "")),
  )
  router = APIRouter(prefix="/api/v1/research", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

  @router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
  async def proxy(path: str, request: Request):
    if not allowed(request.method, path):
      raise HTTPException(404, detail="research_endpoint_unavailable")
    if not target:
      raise HTTPException(503, detail="research_service_unavailable")
    endpoint = (
      {"info": "research-info", "prepare": "research-prepare", "backtest": "research-backtest"}.get(path, path)
      if request.method == "POST"
      else {"info": "research-info"}.get(path, path)
    )
    try:
      async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        result = await client.request(
          request.method,
          target + "/api/v1/" + endpoint,
          params=request.query_params,
          content=await request.body(),
          headers={"Content-Type": "application/json"},
          auth=httpx.BasicAuth(username, password),
        )
    except httpx.RequestError:
      raise HTTPException(503, detail="research_service_unavailable") from None
    if result.status_code in (401, 403):
      # Service authentication must never sign the user's main session out.
      raise HTTPException(502, detail="research_service_auth_failed")
    return Response(result.content, status_code=result.status_code, media_type="application/json")

  app.include_router(router)
