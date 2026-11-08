"""Local-only integration fixture. No exchange, trading RPC or external Bark service."""

import json
import time

import nfi_account.bark as bark
from fastapi import HTTPException

bark.INTERVAL_SECONDS = 1

from smoke_server import app, user_data  # noqa: E402

state_path = user_data / "fixture-bark-state.json"
receipts_path = user_data / "fixture-bark-receipts.json"


def state():
  if state_path.exists():
    return json.loads(state_path.read_text())
  return {"roi_pct": 0.0, "bot_state": "stopped", "clock_offset": 0}


def sample():
  value = state()
  return {key: value[key] for key in ("roi_pct", "bot_state")}


app.state.bark_monitor.sample = sample
app.state.bark_monitor.now = lambda: time.time() + state()["clock_offset"]


@app.post("/fixture-bark/push")
def receive(body: dict):
  if body.get("device_key") != "fixture-device-key":
    raise HTTPException(400)
  receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else []
  receipts.append({key: body[key] for key in ("title", "body", "group")})
  receipts_path.write_text(json.dumps(receipts))
  return {"code": 200, "message": "success"}


@app.get("/fixture-bark/status")
def status():
  receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else []
  with app.state.bark_monitor.store.exclusive():
    runtime = app.state.bark_monitor.store.read()["runtime"]
  return {"receipts": receipts, "runtime": runtime}


@app.post("/fixture-bark/sample")
def update_sample(body: dict):
  current = state()
  current.update({key: body[key] for key in current if key in body})
  state_path.write_text(json.dumps(current))
  return {"success": True}


# Keep the UI fallback after the fixture endpoints imported above.
app.router.routes.sort(key=lambda route: getattr(route, "path", "") == "/{path:path}")


if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
