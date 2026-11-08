"""An isolated browser integration server: real account API, fixture-only trading data."""

import json
import os
from pathlib import Path

import freqtrade
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_api_config
from freqtrade.enums import RunMode
from nfi_account import configure_account_api

fixtures = Path(os.environ["NFI_TEST_FIXTURES"])
ui = Path(freqtrade.__file__).parent / "rpc/api_server/ui/installed"
user_data = Path(os.environ["NFI_TEST_USER_DATA"])
config = {
  "user_data_dir": user_data,
  "dry_run": True,
  "runmode": RunMode.DRY_RUN,
  "api_server": {
    "username": "paper",
    "password": "Initial-paper-pass-123",
    "jwt_secret_key": "isolated-browser-account-integration-secret-key",
    "ws_token": [],
  },
}
app = FastAPI()
app.dependency_overrides[get_api_config] = lambda: config["api_server"]
configure_account_api(app, config)
app.include_router(api_auth.router_login, prefix="/api/v1")


@app.get("/nfi-account-test")
def isolated_test_marker():
  return {"isolated": True, "trading_enabled": False}


@app.get("/ui_version")
def version():
  return {"version": (ui / ".uiversion").read_text().strip()}


@app.get("/api/v1/{endpoint:path}", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])
def bot_fixture(endpoint: str):
  files = {"status": "status_empty", "locks": "locks_empty"}
  if endpoint == "profit_all":
    return {"all": json.loads((fixtures / "profit.json").read_text())}
  if endpoint == "account":
    raise HTTPException(404)
  path = fixtures / (files.get(endpoint, endpoint) + ".json")
  if path.parent == fixtures and path.is_file():
    return json.loads(path.read_text())
  if endpoint == "count":
    return {"current": 0, "max": 6, "total_stake": 0}
  return {}


@app.post("/api/v1/{endpoint:path}", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])
def no_trading_mutations(endpoint: str):
  # Account mutations are registered first. No trade, config or bot control is executable here.
  if endpoint in ("pair_candles", "strategy/NoActionStrategy"):
    return {}
  raise HTTPException(405, "Trading mutations are unavailable in this integration server")


@app.get("/{path:path}")
def frontend(path: str):
  target = (ui / path).resolve()
  if target.is_relative_to(ui.resolve()) and target.is_file():
    return FileResponse(target)
  return FileResponse(ui / "index.html")


if __name__ == "__main__":
  uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
