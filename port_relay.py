"""A fixed TCP relay that lets the chat app's container run with no network of its own (threat model gap 6).

The app container sits on an internal Docker network with no route out. This relay is the only other container on that
network. It forwards exactly the routes it is started with, for example:

    python port_relay.py 8501=localai:8501 11434=host.docker.internal:11434

  8501   the browser on this Mac -> the app's UI (the port is published on 127.0.0.1 only, in docker-compose.yml)
  11434  the app -> Ollama on the host

Bytes are copied as they are (HTTP and WebSockets both work). Nothing is parsed, logged or changed. Every other
destination is unreachable for the app, so a bad dependency inside it can't send data out. Standard library only.
"""

import asyncio
import re
import sys

MAX_CONNECTIONS = 64  # per route; well inside the container's process and memory limits
CONNECT_TIMEOUT = 10
CHUNK = 64 * 1024
_RULE = re.compile(r"^(\d{1,5})=([A-Za-z0-9.-]{1,253}):(\d{1,5})$")


class RuleError(ValueError):
    """A route that isn't LISTEN_PORT=HOST:PORT with ports from 1 to 65535."""


def parse_rules(args) -> list:
    """[(listen_port, host, port)] from 'LISTEN=HOST:PORT' strings. Refuses anything else, and duplicate listen ports."""
    rules, seen = [], set()
    for arg in args:
        m = _RULE.match(arg)
        if not m:
            raise RuleError(f"not LISTEN_PORT=HOST:PORT: {arg!r}")
        listen, host, port = int(m.group(1)), m.group(2), int(m.group(3))
        if not (0 < listen < 65536 and 0 < port < 65536):
            raise RuleError(f"port out of range: {arg!r}")
        if listen in seen:
            raise RuleError(f"listen port used twice: {listen}")
        seen.add(listen)
        rules.append((listen, host, port))
    if not rules:
        raise RuleError("no routes given")
    return rules


async def _pipe(reader, writer):
    try:
        while data := await reader.read(CHUNK):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _handler(host, port, slots):
    async def handle(reader, writer):
        if slots.locked():
            writer.close()
            return
        async with slots:
            try:
                up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
            except (OSError, asyncio.TimeoutError):
                writer.close()
                return
            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
    return handle


async def serve(rules, bind="0.0.0.0", ready=None):
    """Run every route until cancelled. `ready`, if given, is called with [(listen_port, bound_port)] once listening."""
    servers = []
    for listen, host, port in rules:
        srv = await asyncio.start_server(_handler(host, port, asyncio.Semaphore(MAX_CONNECTIONS)), bind, listen)
        servers.append((listen, srv))
    if ready:
        ready([(listen, srv.sockets[0].getsockname()[1]) for listen, srv in servers])
    try:
        await asyncio.gather(*(srv.serve_forever() for _, srv in servers))
    finally:
        for _, srv in servers:
            srv.close()


def main(argv=None) -> int:
    try:
        rules = parse_rules(sys.argv[1:] if argv is None else argv)
    except RuleError as e:
        print(f"port_relay: {e}", file=sys.stderr)
        return 2
    print("port_relay: " + ", ".join(f"{lp} -> {h}:{p}" for lp, h, p in rules), flush=True)
    asyncio.run(serve(rules))
    return 0


if __name__ == "__main__":
    sys.exit(main())
