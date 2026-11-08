"""Prepare a separate OKX spot deployment; never start a bot or submit orders."""

import argparse
import getpass
import json
import logging
import secrets
import shutil
from pathlib import Path

from nfi_live.config import build_config
from nfi_research.recipe import exchange_defaults

LIVE_DIR = Path("/freqtrade/user_data")
SOURCE_DIR = Path("/opt/nfi")


def write_files(directory, source_strategy, config, key, secret, password, passphrase):
  if not key.strip() or not secret.strip() or not passphrase.strip():
    raise ValueError("API Key、Secret 和 OKX Passphrase 不能为空。")
  if not 12 <= len(password) <= 128 or any(ord(c) < 32 or ord(c) == 127 for c in password):
    raise ValueError("后台密码须为 12–128 个字符，且不含控制字符。")
  if any(directory.iterdir()):
    raise ValueError("实盘目录已含文件，拒绝覆盖。请使用原配置或另建目录。")
  strategy = source_strategy.read_bytes()
  credentials = {
    "exchange": {"key": key.strip(), "secret": secret.strip(), "password": passphrase.strip()},
    "api_server": {"username": "live-admin", "password": password, "jwt_secret_key": secrets.token_hex(32)},
  }
  guard = directory / ".prepare.lock"
  with guard.open("x"):
    pass
  created = []
  try:
    for name, data in (("config.json", config), ("credentials.json", credentials)):
      with (directory / name).open("x", encoding="utf-8") as stream:
        created.append(directory / name)
        (directory / name).chmod(0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    (directory / "strategies").mkdir()
    created.append(directory / "strategies")
    (directory / "strategies/NostalgiaForInfinityX8.py").write_bytes(strategy)
    (directory / "logs").mkdir()
    created.append(directory / "logs")
  except Exception:
    for path in reversed(created):
      if path.is_dir():
        shutil.rmtree(path)
      else:
        path.unlink()
    raise
  finally:
    guard.unlink()


def checked_config():
  from freqtrade.configuration import Configuration
  from freqtrade.configuration.config_validation import validate_config_consistency
  from freqtrade.resolvers import StrategyResolver

  logging.disable(logging.CRITICAL)
  config = Configuration(
    {
      "config": [str(LIVE_DIR / "config.json"), str(LIVE_DIR / "credentials.json")],
      "strategy_path": str(LIVE_DIR / "strategies"),
      "user_data_dir": str(LIVE_DIR),
      "db_url": f"sqlite:///{LIVE_DIR}/trades-live.sqlite",
    }
  ).get_config()
  strategy = StrategyResolver.load_strategy(config)
  validate_config_consistency(config)
  if (
    config["dry_run"] is not False
    or config.get("initial_state") != "stopped"
    or config["exchange"]["name"] != "okx"
    or config.get("trading_mode") != "spot"
    or Path(strategy.__file__).resolve() != (LIVE_DIR / "strategies/NostalgiaForInfinityX8.py").resolve()
  ):
    raise ValueError("配置应为 OKX 现货实盘、初始待机，请检查配置及环境变量。")
  print(
    json.dumps(
      {
        "exchange": config["exchange"]["name"],
        "dry_run": config["dry_run"],
        "initial_state": config["initial_state"],
        "strategy": config["strategy"],
        "timeframe": config["timeframe"],
        "available_capital": config["available_capital"],
        "max_open_trades": config["max_open_trades"],
        "recipe_revision": config.get("nfi_recipe_revision"),
      },
      ensure_ascii=False,
      indent=2,
    )
  )
  return config


def check_exchange(config):
  import ccxt

  try:
    exchange = ccxt.okx(
      {
        "apiKey": config["exchange"]["key"],
        "secret": config["exchange"]["secret"],
        "password": config["exchange"]["password"],
        **config["exchange"].get("ccxt_config", {}),
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
      }
    )
    balance = exchange.fetch_balance()
  except ccxt.BaseError:
    raise ValueError("余额查询失败，请检查 API 读取权限、IP 白名单、网络和系统时间。") from None
  free = float(balance.get("USDT", {}).get("free", 0))
  print(f"交易所可用 USDT: {free:.2f}")
  if free < config["available_capital"]:
    raise ValueError("可用 USDT 低于初始预算，请调整预算或划转专用资金。")
  print("余额读取成功；这不能证明交易权限有效，真实成交仍需小额验证。")


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  mode = parser.add_mutually_exclusive_group(required=True)
  mode.add_argument("--capital", type=float, help="机器人初始预算（USDT），后续随已实现盈亏变化")
  mode.add_argument("--check", action="store_true", help="离线加载配置和策略，不连接交易所")
  mode.add_argument("--check-exchange", action="store_true", help="只读取交易所余额，不下单")
  args = parser.parse_args()
  try:
    if args.check or args.check_exchange:
      config = checked_config()
      if args.check_exchange:
        check_exchange(config)
      return
    import rapidjson

    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    if any(LIVE_DIR.iterdir()):
      raise ValueError("实盘目录已含文件，拒绝覆盖。")
    parse_mode = rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS
    base = rapidjson.loads((SOURCE_DIR / "configs/exampleconfig.json").read_text(), parse_mode=parse_mode)
    blacklist = rapidjson.loads((SOURCE_DIR / "configs/blacklist-okx.json").read_text(), parse_mode=parse_mode)[
      "exchange"
    ]["pair_blacklist"]
    source = SOURCE_DIR / "recipes/active.json"
    document = (
      json.loads(source.read_text())
      if source.exists()
      else {"schema_version": 1, "revision": 0, "settings": exchange_defaults({"exchange": {"name": "okx"}})}
    )
    config = build_config(base, blacklist, document, args.capital)
    print(f"配方版本 {document['revision']}；初始预算 {args.capital:g} USDT；首次启动为 stopped。")
    key = getpass.getpass("OKX API Key（输入隐藏）: ")
    secret = getpass.getpass("OKX API Secret（输入隐藏）: ")
    passphrase = getpass.getpass("OKX API Passphrase（输入隐藏）: ")
    password = getpass.getpass("设置独立实盘后台密码（12–128 字符）: ")
    if password != getpass.getpass("再次输入后台密码: "):
      raise ValueError("两次密码不一致。")
    write_files(LIVE_DIR, SOURCE_DIR / "NostalgiaForInfinityX8.py", config, key, secret, password, passphrase)
    print("配置和策略副本已生成；后台用户名 live-admin。下一步执行 --check 和 --check-exchange。")
  except (ValueError, OSError) as error:
    parser.exit(1, f"准备失败: {error}\n")


if __name__ == "__main__":
  main()
