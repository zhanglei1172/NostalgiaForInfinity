"""Read cached strategy facts and persisted fills without driving the trading loop."""

import logging
import re
import threading
from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from freqtrade.enums import State
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Order, PairLocks, Trade
from freqtrade.rpc.api_server import api_auth
from freqtrade.rpc.api_server.deps import get_rpc
from freqtrade.rpc.rpc import RPC
from sqlalchemy import func, select

PAIR = r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+"
REJECTIONS = {
  "grind_coins": "not being in grind mode coins list.",
  "grind_slots": "grind mode slots limit reached.",
  "top_coins": "not being in top coins list.",
  "mode_slots": "insufficient free slots.",
}


class RejectionJournal(logging.Handler):
  """Only retain recognized events, never raw log messages or exception details."""

  def __init__(self):
    super().__init__(logging.INFO)
    self.events = deque(maxlen=100)
    self.guard = threading.Lock()
    self.since = datetime.now(UTC).isoformat()

  def emit(self, record):
    try:
      message = record.getMessage()
      match = re.search(rf"Cancelling entry for ({PAIR}) due to (.+)$", message)
      code = None
      if match:
        pair, reason = match.groups()
        code = next((key for key, text in REJECTIONS.items() if reason == text), None)
        if re.fullmatch(r"slippage -?\d+(?:\.\d+)?%\.?", reason):
          code = "slippage"
      else:
        match = re.fullmatch(rf"User denied entry for ({PAIR})\.", message)
        if match:
          pair, code = match[1], "entry_denied"
      if code is None:
        return
      event = {"at": datetime.fromtimestamp(record.created, UTC).isoformat(), "pair": pair, "reason": code}
      with self.guard:
        # The bot's generic refusal follows NFI's specific reason for the same attempt.
        if code == "entry_denied" and self.events:
          previous = self.events[-1]
          delta = record.created - datetime.fromisoformat(previous["at"]).timestamp()
          if previous["pair"] == pair and previous["reason"] != code and 0 <= delta < 2:
            return
        self.events.append(event)
    except Exception:
      # Diagnostics must never prevent an order or interrupt the trading loop.
      return

  def snapshot(self):
    with self.guard:
      return list(reversed(self.events))


def install_journal():
  journal = RejectionJournal()
  # NFI uses logging.getLogger(__name__); Freqtrade resolves its module to the class name.
  for name in ("NostalgiaForInfinityX8", "freqtrade.freqtradebot"):
    logger = logging.getLogger(name)
    for handler in list(logger.handlers):
      if isinstance(handler, RejectionJournal):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(journal)
  return journal


def text_tag(value):
  return value[:160] if isinstance(value, str) else None


def iso(value):
  if value is None:
    return None
  return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()


def recent_fills():
  # Filled quantity also includes partial executions; show whether the order is still open.
  stamp = func.coalesce(Order.order_filled_date, Order.order_update_date, Order.order_date)
  rows = Trade.session.execute(
    select(Order, Trade)
    .join(Trade, Order.ft_trade_id == Trade.id)
    .where(Order.filled > 0)
    .order_by(stamp.desc(), Order.id.desc())
    .limit(30)
  ).all()
  result = []
  for order, trade in rows:
    exits = [o for o in trade.orders if o.ft_order_side in (trade.exit_side, "stoploss") and (o.filled or 0) > 0]
    # A standing stop order can have an older database id than an earlier partial reduction.
    final_exit = (
      max(exits, key=lambda o: (iso(o.order_filled_date or o.order_update_date or o.order_date) or "", o.id))
      if exits
      else None
    )
    result.append(
      {
        "trade_id": trade.id,
        "pair": order.ft_pair,
        "side": order.side,
        "at": iso(order.order_filled_date or order.order_update_date or order.order_date),
        "filled": order.filled,
        "price": order.average or order.price,
        "order_open": order.ft_is_open,
        "tag": text_tag(order.ft_order_tag),
        "exit_reason": text_tag(trade.exit_reason) if not trade.is_open and order == final_exit else None,
      }
    )
  return result


def pair_snapshot(bot, pair, now, global_reasons, open_pairs):
  reasons = list(global_reasons)
  if pair in open_pairs:
    reasons.append("position_open")
  lock = PairLocks.get_pair_longest_lock(pair, now, side="long")
  if lock:
    reasons.append("pair_locked")
  frame, refreshed = bot.dataprovider.get_analyzed_dataframe(pair, bot.strategy.timeframe)
  item = {
    "pair": pair,
    "candle_at": None,
    "analyzed_at": iso(refreshed) if not frame.empty else None,
    "signal": "unavailable",
    "entry_tag": None,
    "exit_tag": None,
    "reasons": reasons,
    "lock_until": iso(lock.lock_end_time) if lock else None,
  }
  if frame.empty:
    reasons.append("no_analysis")
    return item
  candle = frame.iloc[-1]
  candle_at = candle["date"].to_pydatetime().replace(tzinfo=UTC)
  item.update(
    candle_at=iso(candle_at), entry_tag=text_tag(candle.get("enter_tag")), exit_tag=text_tag(candle.get("exit_tag"))
  )
  entry, exit_, short = (candle.get(name, 0) == 1 for name in ("enter_long", "exit_long", "enter_short"))
  item["signal"] = "conflict" if entry and (exit_ or short) else "entry" if entry else "none"
  offset = bot.config.get("exchange", {}).get("outdated_offset", 5)
  if now - candle_at > timedelta(minutes=timeframe_to_minutes(bot.strategy.timeframe) * 2 + offset):
    reasons.append("stale_candle")
  if not entry:
    reasons.append("no_entry_signal")
  elif exit_ or short:
    reasons.append("signal_conflict")
  else:
    reasons.append("entry_candidate")
  return item


def activity_snapshot(bot, journal):
  now = datetime.now(UTC)
  open_trades = Trade.get_open_trades()
  slots = bot.get_free_open_trades()
  pairs = list(bot.active_pair_whitelist)
  reasons = []
  if bot.state == State.STOPPED:
    reasons.append("stopped")
  elif bot.state == State.PAUSED:
    reasons.append("paused")
  elif bot.state != State.RUNNING:
    reasons.append("reloading")
  if slots == 0:
    reasons.append("slots_full")
  if PairLocks.get_pair_longest_lock("*", now, side="long"):
    reasons.append("global_lock")
  if not pairs:
    reasons.append("empty_pool")
  open_pairs = {trade.pair for trade in open_trades}
  snapshots = [pair_snapshot(bot, pair, now, reasons, open_pairs) for pair in pairs[:80]]
  return {
    "as_of": now.isoformat(),
    "exchange": bot.config["exchange"]["name"],
    "dry_run": bot.config["dry_run"],
    "state": str(bot.state).lower(),
    "strategy": bot.config["strategy"],
    "timeframe": bot.strategy.timeframe,
    "open_trades": len(open_trades),
    "free_slots": slots,
    "pair_count": len(pairs),
    "reasons": reasons,
    "pairs": snapshots,
    "fills": recent_fills(),
    "rejections": journal.snapshot(),
    "journal_since": journal.since,
  }


def configure_activity_api(app, config):
  if str(config.get("runmode")) not in ("dry_run", "live"):
    return
  journal = install_journal()
  router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

  @router.get("/strategy-activity")
  def activity(rpc: Annotated[RPC, Depends(get_rpc)]):
    return activity_snapshot(rpc._freqtrade, journal)

  app.include_router(router)
