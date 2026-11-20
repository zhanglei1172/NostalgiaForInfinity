#!/usr/bin/env python3
"""Create independent Web-managed spot/futures deployments; never modify a running bot."""

import argparse
import importlib.util
import json
import socket
from pathlib import Path


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("command", choices=["create", "list"])
  parser.add_argument("--name")
  parser.add_argument("--mode", choices=["spot", "futures"], default="spot")
  parser.add_argument("--port", type=int, default=18082)
  parser.add_argument("--console-origin", action="append", default=[])
  parser.add_argument("--image", default="nfi-paper:multi")
  parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
  args = parser.parse_args()
  root = args.root.resolve()
  if args.command == "list":
    for path in sorted((root / "user_data/bots").glob("*/compose.json")):
      data = json.loads(path.read_text())
      bot = data["services"]["bot"]
      print(path.parent.name, bot["environment"]["NFI_TRADING_MODE"], bot["ports"][0], str(path))
    return
  if not args.name:
    parser.error("create requires --name")
  module = Path(__file__).resolve().parents[1] / "webserver_extensions/nfi_live/deployment.py"
  spec = importlib.util.spec_from_file_location("deployment", module)
  deployment = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(deployment)
  try:
    deployment.validate_deployment(args.name, args.mode, args.port, args.console_origin, args.image)
    with socket.socket() as probe:
      probe.bind(("127.0.0.1", args.port))
    # Detect a port reserved by another generated project, including stopped projects.
    for path in (root / "user_data/bots").glob("*/compose.json"):
      current = json.loads(path.read_text())
      if f"127.0.0.1:{args.port}:8080" in current["services"]["bot"].get("ports", []):
        raise ValueError("This port is already reserved by another instance")
    result = deployment.create_deployment(root, args.name, args.mode, args.port, args.console_origin, args.image)
  except (ValueError, OSError) as exc:
    parser.error(str(exc))
  print("Created:", result["compose"])
  print("Build:", result["command"], "build bot")
  print("Start management:", result["command"], "up -d bot")
  print("Optional isolated research:", result["command"], "--profile research up -d")
  print("Open:", result["url"])
  print("Create the Web administrator locally; configure the OKX account and budget in Web. Trading stays stopped.")


if __name__ == "__main__":
  main()
