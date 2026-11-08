"""Isolated auth-freeze fixture with an adjustable guard clock; no order engine."""

import json
import time

from nfi_account import _managers
from smoke_server import app, config, user_data

manager = _managers[id(config["api_server"])]
clock_path = user_data / "fixture-auth-clock.json"


def offset():
  return json.loads(clock_path.read_text()) if clock_path.exists() else 0


manager.attempts.now = lambda: time.time() + offset()


@app.get("/nfi-auth-test")
def marker():
  return {"isolated": True, "trading_enabled": False, "retry_after": manager.attempts.remaining()}


@app.post("/fixture-auth/advance")
def advance():
  clock_path.write_text(json.dumps(offset() + 301))
  return {"success": True}


app.router.routes.sort(key=lambda route: getattr(route, "path", "") == "/{path:path}")

if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
