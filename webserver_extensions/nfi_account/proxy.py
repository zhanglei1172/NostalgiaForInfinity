"""Private exchange transport settings, independent of account keys and trading recipes."""

import fcntl
import ipaddress
import json
import logging
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from .credentials import AccountError
from .startup import private_document

LOCK = threading.RLock()
PROTOCOLS = ("socks5h", "socks5", "http", "https")
FIELDS = ("enabled", "protocol", "host", "port", "auth_enabled", "username", "password")
PROXY_KEYS = (
  "proxies",
  "proxyUrl",
  "proxy_url",
  "aiohttp_proxy",
  "httpProxy",
  "httpsProxy",
  "socksProxy",
  "wsProxy",
  "wssProxy",
  "wsSocksProxy",
  "http_proxy",
  "https_proxy",
  "socks_proxy",
  "ws_proxy",
  "wss_proxy",
  "ws_socks_proxy",
  "proxyUrlCallback",
  "httpProxyCallback",
  "httpsProxyCallback",
  "socksProxyCallback",
  "proxy_url_callback",
  "http_proxy_callback",
  "https_proxy_callback",
  "socks_proxy_callback",
)
_runtime = {}
_redactions = set()


def defaults():
  return {
    "enabled": False,
    "protocol": "socks5h",
    "host": "",
    "port": 1080,
    "auth_enabled": False,
    "username": "",
    "password": "",
  }


def validate_settings(value):
  if not isinstance(value, dict) or set(value) != set(FIELDS):
    raise ValueError("Invalid proxy settings")
  data = dict(value)
  if any(type(data[key]) is not bool for key in ("enabled", "auth_enabled")):
    raise ValueError("Invalid switch")
  if data["protocol"] not in PROTOCOLS or type(data["port"]) is not int or not 1 <= data["port"] <= 65535:
    raise ValueError("Invalid proxy transport")
  for key in ("host", "username", "password"):
    if not isinstance(data[key], str) or len(data[key]) > 253 or any(ord(c) < 32 or ord(c) == 127 for c in data[key]):
      raise ValueError("Invalid proxy field")
  host = data["host"].strip()
  if host.startswith("[") and host.endswith("]"):
    host = host[1:-1]
  if host:
    try:
      host = str(ipaddress.ip_address(host))
    except ValueError:
      host = host.encode("idna").decode("ascii").lower()
      if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in host.split(".")
      ):
        raise ValueError("Invalid proxy host") from None
  data["host"] = host
  if data["enabled"] and not host:
    raise ValueError("Proxy host required")
  if data["auth_enabled"] and (not data["username"] or not data["password"]):
    raise ValueError("Proxy credentials required")
  if not data["auth_enabled"]:
    data.update(username="", password="")
  return data


def public_settings(data):
  return {
    **{key: data[key] for key in FIELDS if key not in ("username", "password")},
    "username_configured": bool(data["username"]),
    "password_configured": bool(data["password"]),
  }


def proxy_url(data):
  host = f"[{data['host']}]" if ":" in data["host"] else data["host"]
  auth = ""
  if data["auth_enabled"]:
    auth = f"{quote(data['username'], safe='')}:{quote(data['password'], safe='')}@"
  return f"{data['protocol']}://{auth}{host}:{data['port']}"


class ProxyStore:
  def __init__(self, directory):
    self.directory = Path(directory)
    self.path = self.directory / ".nfi-proxy.json"

  def read(self):
    try:
      data = private_document(self.path)
      if data is None:
        return {
          "schema_version": 1,
          "revision": 0,
          "active_revision": 0,
          "draft": defaults(),
          "active": defaults(),
          "updated_at": None,
          "applied_at": None,
          "last_test_at": 0,
        }
      if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or type(data.get("revision")) is not int
        or data["revision"] < 0
        or type(data.get("active_revision")) is not int
        or not 0 <= data["active_revision"] <= data["revision"]
        or type(data.get("last_test_at")) not in (int, float)
        or not 0 <= data["last_test_at"] < 1e12
      ):
        raise ValueError("Invalid proxy document")
      for key in ("updated_at", "applied_at"):
        if data.get(key) is not None and not isinstance(data[key], str):
          raise ValueError("Invalid timestamp")
      return {
        "schema_version": 1,
        "revision": data["revision"],
        "active_revision": data["active_revision"],
        "draft": validate_settings(data["draft"]),
        "active": validate_settings(data["active"]),
        "updated_at": data["updated_at"],
        "applied_at": data["applied_at"],
        "last_test_at": data["last_test_at"],
      }
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
      raise AccountError("proxy_storage_unavailable", 503) from None

  @contextmanager
  def exclusive(self):
    try:
      with LOCK:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.directory / ".nfi-proxy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
          fcntl.flock(fd, fcntl.LOCK_EX)
          yield
        finally:
          fcntl.flock(fd, fcntl.LOCK_UN)
          os.close(fd)
    except OSError:
      raise AccountError("proxy_storage_unavailable", 503) from None

  def write(self, data):
    temporary = None
    try:
      with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".proxy-", delete=False) as stream:
        temporary = Path(stream.name)
        os.fchmod(stream.fileno(), 0o600)
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.path)
    except (OSError, ValueError):
      raise AccountError("proxy_storage_unavailable", 503) from None
    finally:
      if temporary:
        temporary.unlink(missing_ok=True)

  def save(self, settings, revision):
    with self.exclusive():
      data = self.read()
      if revision != data["revision"]:
        raise AccountError("proxy_revision_conflict", 409)
      data.update(draft=validate_settings(settings), revision=revision + 1, updated_at=datetime.now(UTC).isoformat())
      self.write(data)
      return data


def configure_client(client, settings):
  """Set transports after CCXT construction so credentials never enter configuration logs."""
  for key in PROXY_KEYS:
    setattr(client, key, None)
  client.aiohttp_trust_env = False
  session = getattr(client, "session", None)
  if session is not None and hasattr(session, "trust_env"):
    session.trust_env = False
  if settings["enabled"]:
    url = proxy_url(settings)
    if settings["protocol"].startswith("socks"):
      client.socksProxy = client.wsSocksProxy = url
    else:
      client.httpsProxy = client.wssProxy = url
  return client


def redact(value):
  text = str(value)
  with LOCK:
    secrets = sorted(_redactions, key=len, reverse=True)
  for secret in secrets:
    text = text.replace(secret, "[proxy-redacted]")
  return re.sub(r"(?:https?|socks5h?)://[^\s/'\"]+@", "[proxy-redacted]@", text)


def install_redaction(settings):
  with LOCK:
    if settings["enabled"]:
      _redactions.add(proxy_url(settings))
      if settings["auth_enabled"]:
        for value in (settings["password"], quote(settings["password"], safe="")):
          if len(value) >= 4:
            _redactions.add(value)
  original = logging.getLogRecordFactory()
  if getattr(original, "_nfi_proxy_redaction", False):
    return

  def factory(*args, **kwargs):
    record = original(*args, **kwargs)
    record.msg, record.args = redact(record.getMessage()), ()
    if record.exc_info:
      record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
      record.exc_info = None
    return record

  factory._nfi_proxy_redaction = True
  logging.setLogRecordFactory(factory)


def prepare_proxy(config):
  """Worker hook; retain one settings snapshot for synchronous, asynchronous and WS clients."""
  if os.environ.get("NFI_RECIPE_ROLE") not in ("paper", "live"):
    return
  from freqtrade.exchange.exchange import Exchange

  store = ProxyStore(config["user_data_dir"])
  data = store.read()
  managed = store.path.exists()
  config.update(nfi_proxy_revision=data["active_revision"], nfi_proxy_enabled=data["active"]["enabled"])
  key = str(store.directory.resolve())
  _runtime[key] = {"managed": managed, "settings": deepcopy(data["active"])}
  if managed:
    install_redaction(data["active"])
    for section in ("ccxt_config", "ccxt_sync_config", "ccxt_async_config"):
      transport = config.get("exchange", {}).get(section, {})
      for name in PROXY_KEYS:
        transport.pop(name, None)
  original = Exchange._init_ccxt
  if getattr(original, "_nfi_proxy", False) is True:
    return

  def initialize(exchange, exchange_config, sync, ccxt_kwargs):
    profile = _runtime.get(str(Path(exchange._config["user_data_dir"]).resolve()))
    if profile and profile["managed"]:
      ccxt_kwargs = {k: v for k, v in ccxt_kwargs.items() if k not in PROXY_KEYS}
    client = original(exchange, exchange_config, sync, ccxt_kwargs)
    return configure_client(client, profile["settings"]) if profile and profile["managed"] else client

  initialize._nfi_proxy = True
  Exchange._init_ccxt = initialize


def configure_account_client(client, directory):
  store = ProxyStore(directory)
  if store.path.exists():
    settings = store.read()["active"]
    install_redaction(settings)
    configure_client(client, settings)
  return client
