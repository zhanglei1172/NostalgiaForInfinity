"""Exercise real CCXT HTTPS/WSS through local authenticated proxies, with no exchange access."""

import asyncio
import base64
import collections
import json
import select
import socket
import socketserver
import ssl
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import ccxt
import ccxt.pro
from aiohttp import web
from nfi_account.proxy import defaults
from nfi_account.proxy_api import probe_connection

COUNTS = collections.Counter()
USER, PASSWORD = "proxy-fixture-user", "proxy-fixture:p@ssword"


def read_exact(sock, count):
  data = b""
  while len(data) < count:
    chunk = sock.recv(count - len(data))
    if not chunk:
      raise EOFError()
    data += chunk
  return data


def relay(first, second):
  while True:
    readable, _, _ = select.select([first, second], [], [], 5)
    if not readable:
      return
    for source in readable:
      data = source.recv(65536)
      if not data:
        return
      (second if source is first else first).sendall(data)


class ProxyServer(socketserver.ThreadingTCPServer):
  allow_reuse_address = True
  daemon_threads = True

  def get_request(self):
    sock, address = super().get_request()
    if getattr(self, "tls_context", None) is not None:
      sock = self.tls_context.wrap_socket(sock, server_side=True)
    return sock, address


class Socks(socketserver.BaseRequestHandler):
  def handle(self):
    sock = self.request
    sock.settimeout(5)
    try:
      version, length = read_exact(sock, 2)
      assert version == 5
      methods = read_exact(sock, length)
      assert 2 in methods
      sock.sendall(b"\x05\x02")
      assert read_exact(sock, 1) == b"\x01"
      user = read_exact(sock, read_exact(sock, 1)[0]).decode()
      password = read_exact(sock, read_exact(sock, 1)[0]).decode()
      if (user, password) != (USER, PASSWORD):
        COUNTS["auth_rejected"] += 1
        sock.sendall(b"\x01\x01")
        return
      sock.sendall(b"\x01\x00")
      version, command, _, kind = read_exact(sock, 4)
      assert version == 5 and command == 1
      if kind == 3:
        host = read_exact(sock, read_exact(sock, 1)[0]).decode()
        COUNTS["remote_dns"] += 1
      elif kind == 1:
        host = socket.inet_ntop(socket.AF_INET, read_exact(sock, 4))
      else:
        raise AssertionError("Unexpected destination")
      port = struct.unpack("!H", read_exact(sock, 2))[0]
      assert host in ("fixture.invalid", "127.0.0.1") and port == self.server.target_port
      with socket.create_connection(("127.0.0.1", port), timeout=5) as target:
        sock.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
        COUNTS["socks_tunnels"] += 1
        relay(sock, target)
    except (EOFError, OSError):
      pass


class HttpProxy(socketserver.BaseRequestHandler):
  def handle(self):
    sock = self.request
    sock.settimeout(5)
    try:
      header = b""
      while not header.endswith(b"\r\n\r\n") and len(header) < 8192:
        header += read_exact(sock, 1)
      first, *fields = header.decode().split("\r\n")
      assert first == f"CONNECT fixture.invalid:{self.server.target_port} HTTP/1.1"
      auth = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
      if not any(line.lower() == "proxy-authorization: basic " + auth.lower() for line in fields):
        sock.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")
        return
      with socket.create_connection(("127.0.0.1", self.server.target_port), timeout=5) as target:
        sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        COUNTS["http_tunnels"] += 1
        relay(sock, target)
    except (EOFError, OSError):
      pass


class PublicServer:
  def __init__(self, context):
    self.loop = asyncio.new_event_loop()
    self.context = context
    self.ready = threading.Event()

  def run(self):
    asyncio.set_event_loop(self.loop)
    self.loop.run_until_complete(self.start())
    self.ready.set()
    self.loop.run_forever()
    self.loop.run_until_complete(self.runner.cleanup())
    self.loop.close()

  async def start(self):
    app = web.Application()

    async def public_time(_request):
      COUNTS["public_time"] += 1
      return web.json_response({"code": "0", "data": [{"ts": str(int(time.time() * 1000))}]})

    async def candles(request):
      ws = web.WebSocketResponse()
      await ws.prepare(request)
      async for message in ws:
        data = json.loads(message.data)
        for arg in data.get("args", []):
          COUNTS["public_subscription"] += 1
          await ws.send_json({"event": "subscribe", "arg": arg})
          await ws.send_json(
            {
              "arg": arg,
              "data": [[str(int(time.time() // 300 * 300000)), "100", "101", "99", "100", "10", "1000", "1000", "1"]],
            }
          )
      return ws

    app.router.add_get("/api/v5/public/time", public_time)
    app.router.add_get("/business", candles)
    self.runner = web.AppRunner(app)
    await self.runner.setup()
    self.site = web.TCPSite(self.runner, "127.0.0.1", 0, ssl_context=self.context)
    await self.site.start()
    self.port = self.site._server.sockets[0].getsockname()[1]


def main():
  with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    subprocess.run(
      [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-subj",
        "/CN=fixture.invalid",
        "-keyout",
        str(root / "key.pem"),
        "-out",
        str(root / "cert.pem"),
      ],
      check=True,
      capture_output=True,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / "cert.pem", root / "key.pem")
    public = PublicServer(context)
    thread = threading.Thread(target=public.run, daemon=True)
    thread.start()
    assert public.ready.wait(5)
    sync_factory, async_factory = ccxt.okx, ccxt.pro.okx

    def factory(original, host):
      def make(options):
        client = original({**options, "verify": False})
        client.urls["api"]["rest"] = f"https://{host}:{public.port}"
        if hasattr(client, "watch_ohlcv"):
          client.ssl_context = False
          client.urls["api"]["ws"] = f"wss://{host}:{public.port}"
        return client

      return make

    try:
      for protocol, handler in (("socks5h", Socks), ("socks5", Socks), ("http", HttpProxy), ("https", HttpProxy)):
        with ProxyServer(("127.0.0.1", 0), handler) as server:
          server.target_port = public.port
          if protocol == "https":
            server.tls_context = context
          proxy_thread = threading.Thread(target=server.serve_forever, daemon=True)
          proxy_thread.start()
          host = "127.0.0.1" if protocol == "socks5" else "fixture.invalid"
          settings = {
            **defaults(),
            "enabled": True,
            "protocol": protocol,
            "host": "127.0.0.1",
            "port": server.server_address[1],
            "auth_enabled": True,
            "username": USER,
            "password": PASSWORD,
          }
          with (
            patch("nfi_account.proxy_api.ccxt.okx", side_effect=factory(sync_factory, host)),
            patch("nfi_account.proxy_api.ccxt.pro.okx", side_effect=factory(async_factory, host)),
          ):
            result = probe_connection(settings)
          assert result["success"], {"protocol": protocol, "result": result}
          server.shutdown()
          proxy_thread.join(5)
      assert COUNTS["public_time"] == 8
      assert COUNTS["public_subscription"] == 4
      # Async REST and WSS may reuse the same authenticated tunnel.
      assert COUNTS["remote_dns"] >= 2
      assert COUNTS["socks_tunnels"] >= 4
      assert COUNTS["http_tunnels"] >= 4
    finally:
      public.loop.call_soon_threadsafe(public.loop.stop)
      thread.join(5)
    print(
      "PASS: native CCXT sync/async HTTPS and WebSocket candles through authenticated SOCKS5h, SOCKS5, HTTP and HTTPS CONNECT; proxy DNS and special-character credentials; no external network or orders"
    )


if __name__ == "__main__":
  main()
