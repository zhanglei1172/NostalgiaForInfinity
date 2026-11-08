"""Download NFI candles with enough warm-up history for each individual timeframe."""

import logging
import re
import threading
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from freqtrade.rpc.api_server import api_auth
from pydantic import BaseModel, ConfigDict, model_validator

from .recipe import RecipeStore, recipe_config

TIMEFRAMES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
WARMUP_CANDLES = 900
logger = logging.getLogger(__name__)


class PrepareRequest(BaseModel):
  model_config = ConfigDict(extra="forbid")
  start_date: date
  end_date: date

  @model_validator(mode="after")
  def valid_range(self):
    if self.start_date >= self.end_date or self.end_date > date.today():
      raise ValueError("Select a completed date range; the end date is exclusive")
    if (self.end_date - self.start_date).days > 3 * 366:
      raise ValueError("Select at most three years per download")
    return self


class Preparation:
  def __init__(self, config):
    self.config = config
    self.lock = threading.RLock()
    self.status = {"running": False, "status": "idle", "timeframe": None, "completed": 0, "total": 5, "error": None}

  @staticmethod
  def validate_timeframe(config, payload, timeframe):
    from freqtrade.data.history.datahandlers import get_datahandler
    from freqtrade.enums import CandleType

    handler = get_datahandler(config["datadir"], config.get("dataformat_ohlcv"))
    for pair in config["exchange"]["pair_whitelist"]:
      first, last, count = handler.ohlcv_data_min_max(pair, timeframe, CandleType.SPOT)
      if (
        not count
        or first > datetime.combine(payload.start_date, datetime.min.time(), UTC)
        or last
        < datetime.combine(payload.end_date, datetime.min.time(), UTC) - timedelta(minutes=TIMEFRAMES[timeframe])
      ):
        raise ValueError("Incomplete research candles")

  def start(self, payload):
    with self.lock:
      if self.status["running"]:
        raise HTTPException(409, detail="research_download_running")
      self.status = {
        "running": True,
        "status": "running",
        "timeframe": None,
        "completed": 0,
        "total": 5,
        "error": None,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
      }

  def run(self, payload):
    from freqtrade.data.history.history_utils import download_data
    from freqtrade.rpc.api_server.deps import get_exchange

    try:
      config = deepcopy(self.config)
      config.update(pairs=config["exchange"]["pair_whitelist"], erase=False, download_trades=False, new_pairs_days=30)
      exchange = get_exchange(config)
      for index, (timeframe, minutes) in enumerate(TIMEFRAMES.items()):
        with self.lock:
          self.status.update(timeframe=timeframe, completed=index)
        start = datetime.combine(payload.start_date, datetime.min.time(), UTC) - timedelta(
          minutes=minutes * WARMUP_CANDLES
        )
        config.update(
          timeframes=[timeframe], timerange=start.strftime("%Y%m%d") + "-" + payload.end_date.strftime("%Y%m%d")
        )
        # Extend both ends of an existing data set without erasing downloaded history.
        for prepend in (True, False):
          config["prepend_data"] = prepend
          download_data(config, exchange)
        # Upstream logs individual download errors instead of always raising them.
        self.validate_timeframe(config, payload, timeframe)
      with self.lock:
        self.status.update(running=False, status="success", completed=len(TIMEFRAMES))
    except Exception:
      logger.exception("Research candle preparation failed")
      with self.lock:
        self.status.update(running=False, status="failed", error="research_data_download_failed")

  def info(self):
    with self.lock:
      return {
        "recipe_revision": self.config.get("nfi_recipe_revision", 0),
        "exchange": self.config["exchange"]["name"],
        "trading_mode": self.config.get("trading_mode", "spot"),
        "pairs": self.config["exchange"]["pair_whitelist"],
        "timeframes": list(TIMEFRAMES),
        "stake_currency": self.config["stake_currency"],
        "starting_balance": self.config.get("dry_run_wallet", 10000),
        "max_open_trades": self.config["max_open_trades"],
        "fee": self.config.get("fee", 0.001),
        "preparation": dict(self.status),
      }


def configure_worker(app, config):
  from freqtrade.rpc.api_server.api_backtest import api_delete_backtest, api_start_backtest
  from freqtrade.rpc.api_server.api_schemas import BacktestRequest
  from freqtrade.rpc.api_server.webserver_bgwork import ApiBG

  worker = Preparation(config)
  store = RecipeStore(config)

  def current_config():
    return recipe_config(config, store.read(), research=True)

  router = APIRouter(prefix="/api/v1", dependencies=[Depends(api_auth.http_basic_or_jwt_token)])

  @router.get("/research-info")
  def info():
    with worker.lock:
      if not worker.status["running"]:
        current = current_config()
        if worker.config.get("nfi_recipe_revision") != current["nfi_recipe_revision"]:
          worker.status = {
            "running": False,
            "status": "idle",
            "timeframe": None,
            "completed": 0,
            "total": 5,
            "error": None,
          }
        worker.config = current
    return worker.info()

  @router.post("/research-prepare")
  def prepare(payload: PrepareRequest, background: BackgroundTasks):
    with worker.lock:
      if ApiBG.analysis_running or worker.status["running"]:
        raise HTTPException(409, detail="research_backtest_running")
      worker.config = current_config()
      worker.start(payload)
    background.add_task(worker.run, payload)
    return worker.info()["preparation"]

  @router.post("/research-backtest")
  async def backtest(payload: BacktestRequest, background: BackgroundTasks):
    with worker.lock:
      if worker.status["running"] or ApiBG.analysis_running:
        raise HTTPException(409, detail="research_job_running")
      snapshot = current_config()
      if not payload.timerange or not re.fullmatch(r"\d{8}-\d{8}", payload.timerange):
        raise HTTPException(422, detail="research_date_range_invalid")
      try:
        dates = PrepareRequest(
          start_date=datetime.strptime(payload.timerange[:8], "%Y%m%d").date(),
          end_date=datetime.strptime(payload.timerange[9:], "%Y%m%d").date(),
        )
      except ValueError:
        raise HTTPException(422, detail="research_date_range_invalid") from None
      try:
        for timeframe in TIMEFRAMES:
          worker.validate_timeframe(snapshot, dates, timeframe)
      except (ValueError, OSError):
        raise HTTPException(409, detail="research_data_required") from None
      # Upstream caches candles by timeframe/date only; a changed pair universe must reload them.
      api_delete_backtest()
      settings = payload.model_copy(
        update={"max_open_trades": snapshot["max_open_trades"], "stake_amount": "unlimited", "timeframe": "5m"}
      )
      snapshot["original_config"].update(settings.model_dump(exclude_none=True, exclude={"strategy_params"}))
      return await api_start_backtest(settings, background, config=snapshot)

  app.include_router(router)
