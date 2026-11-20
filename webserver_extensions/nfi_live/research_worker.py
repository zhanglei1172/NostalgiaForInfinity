"""Run an instance's optional research service using public settings and no exchange credentials."""

import json
import os
from pathlib import Path

import rapidjson

from .storage import atomic_json, read_json
from .trading import apply_trading_settings, instance_mode


def build_research_config(source, directory, auth, mode):
  config = json.loads((source / "configs/research.json").read_text())
  config.pop("add_config_files", None)
  blacklist = rapidjson.loads(
    (source / "configs/blacklist-okx.json").read_text(),
    parse_mode=rapidjson.PM_COMMENTS | rapidjson.PM_TRAILING_COMMAS,
  )
  config["exchange"].update(blacklist["exchange"])
  config["exchange"].update(key="", secret="", password="")
  config.update(user_data_dir=str(directory), initial_state="stopped", strategy="NostalgiaForInfinityX8")
  apply_trading_settings(config, mode, 1.0)
  if mode == "futures":
    config["exchange"]["pair_whitelist"] = [pair + ":USDT" for pair in config["exchange"]["pair_whitelist"]]
  paths = ["/freqtrade/strategies", str(source)]
  config["strategy_path"] = paths[0] if (Path(paths[0]) / "NostalgiaForInfinityX8.py").exists() else paths[1]
  config["api_server"].update(auth, listen_ip_address="0.0.0.0", listen_port=8080, CORS_origins=[])
  return config


def main():
  source = Path(os.environ.get("NFI_LIVE_SOURCE", "/opt/nfi"))
  directory = Path("/freqtrade/user_data")
  auth = read_json(os.environ["NFI_RESEARCH_AUTH_FILE"])
  config = build_research_config(source, directory, auth, instance_mode())
  path = directory / "research-config.json"
  atomic_json(path, config)
  os.environ["NFI_RECIPE_ROLE"] = "research"
  os.execvp("freqtrade", ["freqtrade", "webserver", "--config", str(path), "--userdir", str(directory)])


if __name__ == "__main__":
  main()
