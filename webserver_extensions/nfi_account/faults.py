"""Observe exchange outcomes without retrying calls, sending HTTP, or retaining raw errors."""

import inspect
import re
import secrets
import threading
import time
from collections import deque
from functools import wraps
from pathlib import Path

import ccxt

PAIR = re.compile(r"[A-Za-z0-9_.-]{1,30}/[A-Za-z0-9_.:-]{1,30}")
CODES = {
  "insufficient_funds": "交易所余额不足",
  "order_rejected": "交易所拒绝订单，请检查最小下单量、精度及交易限制",
  "order_failed": "订单操作失败",
  "order_uncertain": "订单请求发生网络异常，执行结果尚待机器人核对",
  "authentication": "交易所身份验证或权限检查失败",
  "rate_limited": "交易所请求被限流",
  "connection": "交易所连接超时或网络异常",
  "exchange_request": "交易所请求失败",
  "initialization": "实盘服务初始化失败，请检查账户配置及服务日志",
}
OPERATIONS = {
  "create_order": "下单",
  "cancel_order": "撤单",
  "create_stoploss": "提交止损订单",
  "cancel_stoploss_order": "撤销止损订单",
  "get_balances": "读取余额",
  "fetch_order": "查询订单",
  "fetch_orders": "查询订单记录",
  "fetch_stoploss_order": "查询止损订单",
  "get_tickers": "读取行情",
  "fetch_ticker": "读取行情",
  "fetch_l2_order_book": "读取盘口",
  "_async_get_candle_history": "读取 K 线",
  "initialization": "初始化实盘服务",
}
ORDER_METHODS = {"create_order", "cancel_order", "create_stoploss", "cancel_stoploss_order"}
LIMIT = 256
_journals = {}
_guard = threading.RLock()


def valid_pair(value):
  return value if isinstance(value, str) and PAIR.fullmatch(value) else None


def failure_code(exc):
  from freqtrade.exceptions import DDosProtection, InsufficientFundsError, InvalidOrderException, TemporaryError

  chain, seen = [], set()
  while exc is not None and id(exc) not in seen and len(chain) < 8:
    seen.add(id(exc))
    chain.append(exc)
    exc = exc.__cause__ or exc.__context__
  if any(isinstance(e, (ccxt.AuthenticationError, ccxt.PermissionDenied)) for e in chain):
    return "authentication"
  if any(isinstance(e, (ccxt.InsufficientFunds, InsufficientFundsError)) for e in chain):
    return "insufficient_funds"
  if any(isinstance(e, (ccxt.RateLimitExceeded, ccxt.DDoSProtection, DDosProtection)) for e in chain):
    return "rate_limited"
  if any(isinstance(e, (ccxt.NetworkError,)) for e in chain):
    return "connection"
  if any(isinstance(e, (ccxt.InvalidOrder, InvalidOrderException)) for e in chain):
    return "order_rejected"
  if any(isinstance(e, (ccxt.BaseError, TemporaryError)) for e in chain):
    return "exchange_request"
  return None


class FaultJournal:
  def __init__(self, now=time.time):
    self.now = now
    self.guard = threading.Lock()
    self.observations = {}
    self.trades = deque(maxlen=64)

  def record(self, operation, pair=None, timeframe=None, code=None, trade=False):
    pair = valid_pair(pair)
    timeframe = timeframe if isinstance(timeframe, str) and re.fullmatch(r"[0-9]{1,4}[smhdwM]", timeframe) else ""
    source = f"{operation}:{pair or ''}:{timeframe}"
    now = self.now()
    with self.guard:
      previous = self.observations.get(source, {})
      self.observations[source] = {
        "active": code is not None,
        "since": previous["since"] if code and previous.get("active") else now,
        "at": now,
        "operation": operation,
        "pair": pair,
        "code": code,
      }
      if trade and code:
        self.trades.append(
          {"id": secrets.token_hex(12), "at": now, "operation": operation, "pair": pair, "code": code}
        )
      if len(self.observations) > LIMIT:
        oldest = min(self.observations, key=lambda key: self.observations[key]["at"])
        self.observations.pop(oldest)

  def snapshot(self):
    with self.guard:
      return {
        "observations": {key: dict(value) for key, value in self.observations.items()},
        "trades": list(self.trades),
      }


def journal_for(directory):
  key = str(Path(directory).resolve())
  with _guard:
    if key not in _journals:
      _journals[key] = FaultJournal()
    return _journals[key]


def observe(exchange, operation, args, kwargs, exc=None, result=None):
  # This callback must never change an exchange return value or exception.
  try:
    config = exchange._config
    if os_role() not in ("paper", "live") or "user_data_dir" not in config:
      return
    journal = journal_for(config["user_data_dir"])
    pair = kwargs.get("pair")
    if pair is None:
      index = 1 if operation in ("cancel_order", "cancel_stoploss_order", "fetch_order", "fetch_stoploss_order") else 0
      pair = args[index] if len(args) > index else None
    timeframe = kwargs.get("timeframe") or (
      args[1] if operation == "_async_get_candle_history" and len(args) > 1 else None
    )
    code = failure_code(exc) if exc else None
    trade = operation in ORDER_METHODS
    if exc and not code and trade:
      code = "order_failed"
    if exc and (not code or not trade and code in ("order_rejected", "insufficient_funds")):
      return
    if trade and isinstance(result, dict) and result.get("status") == "rejected":
      code = "order_rejected"
    # A failed order request may already have reached the exchange. Never label it
    # a definite rejection and never retry it from this observer.
    if trade and code in ("connection", "exchange_request"):
      journal.record(operation, pair, timeframe, "order_uncertain", trade=True)
      journal.record(operation, pair, timeframe, code)
    else:
      journal.record(operation, pair, timeframe, code, trade=trade)
  except Exception:
    return


def os_role():
  import os

  return os.environ.get("NFI_RECIPE_ROLE")


def wrap_method(original, operation):
  if inspect.iscoroutinefunction(original):

    @wraps(original)
    async def asynchronous(self, *args, **kwargs):
      try:
        result = await original(self, *args, **kwargs)
      except Exception as exc:
        observe(self, operation, args, kwargs, exc=exc)
        raise
      observe(self, operation, args, kwargs, result=result)
      return result

    wrapped = asynchronous
  else:

    @wraps(original)
    def synchronous(self, *args, **kwargs):
      try:
        result = original(self, *args, **kwargs)
      except Exception as exc:
        observe(self, operation, args, kwargs, exc=exc)
        raise
      observe(self, operation, args, kwargs, result=result)
      return result

    wrapped = synchronous
  wrapped._nfi_fault_observer = True
  return wrapped


def install_fault_hooks(config):
  if os_role() not in ("paper", "live") or str(config.get("runmode")) not in ("dry_run", "live"):
    return
  from freqtrade.exchange.exchange import Exchange
  from freqtrade.exchange.okx import Okx

  with _guard:
    for cls in (Exchange, Okx):
      for operation in OPERATIONS:
        original = cls.__dict__.get(operation)
        if callable(original) and not getattr(original, "_nfi_fault_observer", False):
          setattr(cls, operation, wrap_method(original, operation))


def operational_snapshot(config, role):
  from .startup import private_document

  directory = config["user_data_dir"]
  journal = journal_for(directory)
  if role == "live":
    status = private_document(Path(directory) / ".nfi-live-status.json") or {}
    if status.get("phase") == "error":
      journal.record("initialization", code="initialization")
    elif status.get("phase") == "ready":
      journal.record("initialization")
  return journal.snapshot()
