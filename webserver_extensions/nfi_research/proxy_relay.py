"""Optional Linux Docker bridge relay to a host-loopback HTTP proxy."""

import asyncio
import ipaddress
import os


async def relay(reader, writer):
  try:
    upstream_reader, upstream_writer = await asyncio.wait_for(
      asyncio.open_connection("127.0.0.1", int(os.environ.get("NFI_PROXY_HOST_PORT", "7890"))), 10
    )
  except (OSError, TimeoutError):
    writer.close()
    return

  async def copy(source, target):
    while data := await asyncio.wait_for(source.read(65536), 300):
      target.write(data)
      await target.drain()

  tasks = [asyncio.create_task(copy(reader, upstream_writer)), asyncio.create_task(copy(upstream_reader, writer))]
  try:
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
  finally:
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    writer.close()
    upstream_writer.close()


async def main():
  address = os.environ.get("NFI_PROXY_BIND", "172.17.0.1")
  if not ipaddress.ip_address(address).is_private or address in ("0.0.0.0", "::"):
    raise ValueError("Bind to the private Docker bridge address only")
  server = await asyncio.start_server(
    relay, address, int(os.environ.get("NFI_PROXY_LISTEN_PORT", "17890")), limit=65536
  )
  async with server:
    await server.serve_forever()


if __name__ == "__main__":
  asyncio.run(main())
