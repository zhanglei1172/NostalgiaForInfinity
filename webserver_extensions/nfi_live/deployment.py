"""Generate isolated Compose projects without granting Web servers Docker access."""

import json
import os
import re
import secrets
import shlex
import shutil
from pathlib import Path
from urllib.parse import urlsplit


def validate_deployment(name, mode, port, origins, image):
  if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", name):
    raise ValueError("Instance name must be 1–31 lowercase letters, digits or hyphens, starting with a letter")
  if mode not in ("spot", "futures") or type(port) is not int or not 1024 <= port <= 65535:
    raise ValueError("Choose spot/futures and an unused port between 1024 and 65535")
  if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/@-]{0,200}", image):
    raise ValueError("Invalid Docker image reference")
  if len(origins) > 20:
    raise ValueError("Choose at most 20 console origins")
  for origin in origins:
    parts = urlsplit(origin)
    if (
      parts.scheme not in ("http", "https")
      or not parts.hostname
      or parts.username is not None
      or parts.password is not None
      or parts.path not in ("", "/")
      or parts.query
      or parts.fragment
      or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in origin)
    ):
      raise ValueError("Console origins must be exact HTTP(S) origins without a path or credentials")
    if parts.port == 0:
      raise ValueError("Invalid console port")


def compose_document(root, name, mode, port, origins, image):
  validate_deployment(name, mode, port, origins, image)
  root = Path(root).resolve()
  directory = root / "user_data/bots" / name
  common = {
    "image": image,
    "pull_policy": "never",
    "restart": "unless-stopped",
    "dns": ["${NFI_DNS_SERVER:-1.1.1.1}"],
    "extra_hosts": ["host.docker.internal:host-gateway"],
    "stop_grace_period": "40s",
    "healthcheck": {
      "test": ["CMD", "curl", "-f", "http://127.0.0.1:8080/api/v1/ping"],
      "interval": "30s",
      "timeout": "5s",
      "retries": 3,
      "start_period": "30s",
    },
  }
  source = [
    f"{root}/configs:/opt/nfi/configs:ro",
    f"{root}/NostalgiaForInfinityX8.py:/opt/nfi/NostalgiaForInfinityX8.py:ro",
    f"{directory}/research-auth.json:/run/nfi/research-auth.json:ro",
  ]
  return {
    "name": "nfi-" + name,
    "services": {
      "bot": {
        **common,
        "build": {"context": str(root), "dockerfile": "docker/Dockerfile.custom"},
        "cpus": 2,
        "mem_limit": "3g",
        "ports": [f"127.0.0.1:{port}:8080"],
        "environment": {
          "NFI_RECIPE_ROLE": "live",
          "NFI_INSTANCE_ID": name,
          "NFI_TRADING_MODE": mode,
          "NFI_CONSOLE_ORIGINS": json.dumps(origins),
          "NFI_RESEARCH_URL": "http://research:8080",
          "NFI_RESEARCH_AUTH_FILE": "/run/nfi/research-auth.json",
          "FREQTRADE__INITIAL_STATE": "stopped",
        },
        "volumes": [f"{directory}/live:/freqtrade/user_data", *source],
        "entrypoint": ["python", "-m", "nfi_live"],
      },
      "research": {
        **common,
        "profiles": ["research"],
        "cpus": 2,
        "mem_limit": "6g",
        "environment": {
          "NFI_RECIPE_ROLE": "research",
          "NFI_TRADING_MODE": mode,
          "NFI_RESEARCH_INSTANCE_DIR": "/opt/nfi/instance",
          "NFI_RESEARCH_AUTH_FILE": "/run/nfi/research-auth.json",
        },
        "volumes": [
          f"{directory}/research:/freqtrade/user_data",
          f"{directory}/live/research-public:/opt/nfi/instance:ro",
          f"{directory}/live/strategies:/freqtrade/strategies:ro",
          *source,
        ],
        "depends_on": {"bot": {"condition": "service_healthy"}},
        "entrypoint": ["python", "-m", "nfi_live.research_worker"],
      },
    },
  }


def create_deployment(root, name, mode, port, origins, image="nfi-paper:multi"):
  root = Path(root).resolve()
  document = compose_document(root, name, mode, port, origins, image)
  directory = root / "user_data/bots" / name
  # Never overwrite an existing instance, its account files, or its ledger.
  directory.mkdir(parents=True, mode=0o700, exist_ok=False)
  try:
    for child in ("live", "live/strategies", "live/research-public", "research"):
      (directory / child).mkdir(mode=0o700, exist_ok=True)
    shutil.copyfile(root / "NostalgiaForInfinityX8.py", directory / "live/strategies/NostalgiaForInfinityX8.py")
    auth = {"username": "research-" + name, "password": secrets.token_hex(32), "jwt_secret_key": secrets.token_hex(32)}
    auth_path = directory / "research-auth.json"
    with auth_path.open("x") as stream:
      auth_path.chmod(0o600)
      json.dump(auth, stream)
    path = directory / "compose.json"
    with path.open("x") as stream:
      json.dump(document, stream, indent=2)
      stream.write("\n")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
      # The supplied Docker image runs as ftuser (1000), including on root-operated VPS hosts.
      for child in [*directory.rglob("*"), directory]:
        os.chown(child, 1000, 1000)
  except Exception:
    shutil.rmtree(directory)
    raise
  command = shlex.join(["docker", "compose", "-f", str(path)])
  return {"directory": str(directory), "compose": str(path), "command": command, "url": f"http://127.0.0.1:{port}"}
