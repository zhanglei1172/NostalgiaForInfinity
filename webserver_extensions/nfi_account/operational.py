"""Persist bounded incident queues and recovery state for optional Bark alerts."""

import math
import re
import secrets
from datetime import UTC, datetime

from .faults import CODES, LIMIT, OPERATIONS, valid_pair

CONNECTION_CODES = {"authentication", "rate_limited", "connection", "exchange_request", "initialization"}
INCIDENT_EVENTS = ("trade_error", "exchange_error", "recovery")


def empty_operational():
  return {"faults": {}, "seen": [], "trades": [], "trade_since": 0, "outage": None, "recovery": None}


def finite(value):
  return type(value) in (int, float) and math.isfinite(value) and value >= 0


def valid_context(value):
  return value is None or (
    isinstance(value, dict)
    and set(value) == {"code", "operation", "pair", "count"}
    and value["code"] in CODES
    and value["operation"] in OPERATIONS
    and (value["pair"] is None or valid_pair(value["pair"]) is not None)
    and type(value["count"]) is int
    and 1 <= value["count"] <= LIMIT
  )


def valid_incident(value, trade=False):
  return (
    isinstance(value, dict)
    and value.get("code") in CODES
    and value.get("operation") in OPERATIONS
    and (value.get("pair") is None or valid_pair(value["pair"]) is not None)
    and finite(value.get("at"))
    and (
      isinstance(value.get("id"), str) and re.fullmatch(r"[0-9a-f]{24}", value["id"])
      if trade
      else finite(value.get("since"))
    )
  )


def validate_operational(value):
  if not isinstance(value, dict) or not finite(value.get("trade_since")):
    raise ValueError("Invalid operational notification state")
  faults, seen, trades = value.get("faults"), value.get("seen"), value.get("trades")
  if (
    not isinstance(faults, dict)
    or len(faults) > LIMIT
    or not isinstance(seen, list)
    or len(seen) > 128
    or any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{24}", item) for item in seen)
    or not isinstance(trades, list)
    or len(trades) > 64
    or any(not valid_incident(item, trade=True) for item in trades)
  ):
    raise ValueError("Invalid incident queue")
  for source, item in faults.items():
    if (
      not isinstance(source, str)
      or len(source) > 120
      or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", source)
      or not valid_incident(item)
      or item["code"] not in CONNECTION_CODES
    ):
      raise ValueError("Invalid exchange incident")
  for key in ("outage", "recovery"):
    incident = value.get(key)
    if incident is not None and (
      not isinstance(incident, dict)
      or not isinstance(incident.get("id"), str)
      or not re.fullmatch(r"[0-9a-f]{24}", incident["id"])
      or not finite(incident.get("since"))
      or type(incident.get("notified")) is not bool
      or key == "recovery"
      and not finite(incident.get("resolved_at"))
    ):
      raise ValueError("Invalid recovery state")
  return value


def advance_operational(runtime, snapshot, settings, now):
  ops = runtime.setdefault("operational", empty_operational())
  if settings["trade_error_enabled"]:
    seen = set(ops["seen"])
    for item in snapshot.get("trades", []):
      if not valid_incident(item, trade=True) or item["id"] in seen:
        continue
      seen.add(item["id"])
      ops["seen"].append(item["id"])
      if item["at"] >= ops["trade_since"]:
        ops["trades"].append(item)
    ops["seen"] = ops["seen"][-128:]
    ops["trades"] = ops["trades"][-64:]
  else:
    ops["trades"] = []
  faults = ops["faults"]
  if settings["exchange_error_enabled"]:
    for source, item in snapshot.get("observations", {}).items():
      if not isinstance(item, dict) or not finite(item.get("at")):
        continue
      previous = faults.get(source)
      if previous and item["at"] < previous["at"]:
        continue
      if item.get("active") and item.get("code") in CONNECTION_CODES and valid_incident(item):
        faults[source] = {**item, "since": previous["since"] if previous else item["since"]}
      else:
        faults.pop(source, None)
    if len(faults) > LIMIT:
      ops["faults"] = faults = dict(sorted(faults.items(), key=lambda entry: entry[1]["at"], reverse=True)[:LIMIT])
    if faults:
      ops["recovery"] = None
      if ops["outage"] is None:
        ops["outage"] = {
          "id": secrets.token_hex(12),
          "since": min(v["since"] for v in faults.values()),
          "notified": False,
        }
    elif ops["outage"] is not None:
      outage = ops["outage"]
      if outage["notified"] and settings["recovery_enabled"]:
        ops["recovery"] = {**outage, "resolved_at": now}
      ops["outage"] = None
  else:
    ops.update(faults={}, outage=None, recovery=None)
    faults = ops["faults"]
  if not settings["recovery_enabled"]:
    ops["recovery"] = None
  connection_ready = any(
    item["code"] in ("authentication", "initialization")
    or now - item["since"] >= settings["exchange_grace_minutes"] * 60
    for item in faults.values()
  )
  return {
    "trade_error": bool(ops["trades"]),
    "exchange_error": bool(faults) and (connection_ready or ops["outage"]["notified"]),
    "recovery": ops["recovery"] is not None and not faults,
  }


def incident_context(ops, event):
  if event == "trade_error":
    values = ops["trades"]
  elif event == "exchange_error":
    values = list(ops["faults"].values())
  else:
    return None
  latest = max(values, key=lambda value: value["at"])
  return {key: latest[key] for key in ("code", "operation", "pair")} | {"count": len(values)}


def incident_message(ops, event, now):
  if event == "recovery":
    recovery = ops["recovery"]
    duration = max(0, int(recovery["resolved_at"] - recovery["since"]))
    return "交易所连接恢复", f"已观察到此前失败的操作成功，异常持续约 {duration} 秒。"
  context = incident_context(ops, event)
  operation = OPERATIONS[context["operation"]]
  pair = f"\n币对：{context['pair']}" if context["pair"] else ""
  body = f"操作：{operation}{pair}\n原因：{CODES[context['code']]}"
  if event == "trade_error":
    at = max(item["at"] for item in ops["trades"])
    body += f"\n待通知订单异常：{context['count']} 次"
    body += f"\n最近发生：{datetime.fromtimestamp(at, UTC).isoformat()}"
    return "订单操作异常", body
  body += f"\n受影响操作：{context['count']} 项"
  body += f"\n已观察到异常约 {max(0, int(now - ops['outage']['since']))} 秒"
  return "交易所连接或初始化异常", body


def claim_incident(rule, ops, event):
  if event == "trade_error":
    rule["pending_ids"] = [item["id"] for item in ops["trades"]]
  elif event in ("exchange_error", "recovery"):
    rule["pending_incident"] = ops["outage" if event == "exchange_error" else "recovery"]["id"]


def delivered_incident(rule, ops, event):
  if event == "trade_error":
    claimed = set(rule.pop("pending_ids", []))
    ops["trades"] = [item for item in ops["trades"] if item["id"] not in claimed]
    rule["latched"] = False
  elif event == "exchange_error":
    if ops["outage"] and ops["outage"]["id"] == rule.get("pending_incident"):
      ops["outage"]["notified"] = True
  elif event == "recovery":
    if ops["recovery"] and ops["recovery"]["id"] == rule.get("pending_incident"):
      ops["recovery"] = None
    rule["latched"] = False
