"""HTTP CONNECT egress proxy with a per-listener allowlist (03 section 5.3).

One listener per agent or helper container, on a free port of `network.proxy_ports`. Only
`CONNECT host:443` to an allowed host is tunnelled (exact host or `*.domain` suffix); plain HTTP
and every other method are refused. Every decision is logged and counted. No TLS interception.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger("egress")

Opener = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


def host_allowed(host: str, allow: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for rule in allow:
        rule = rule.lower()
        if rule.startswith("*."):
            if host.endswith(rule[1:]) and host != rule[2:]:
                return True
        elif host == rule:
            return True
    return False


@dataclass(slots=True)
class Decision:
    host: str
    port: int
    allowed: bool
    bytes: int = 0


@dataclass(slots=True)
class ProxyStats:
    decisions: list[Decision] = field(default_factory=list)

    @property
    def denied(self) -> int:
        return sum(1 for d in self.decisions if not d.allowed)

    @property
    def allowed(self) -> int:
        return sum(1 for d in self.decisions if d.allowed)


class EgressListener:
    """A started listener. Use `async with EgressProxy.listen(...)` or call `close()`."""

    def __init__(
        self,
        server: asyncio.Server,
        port: int,
        stats: ProxyStats,
        tasks: set[asyncio.Task[None]],
    ) -> None:
        self._server = server
        self.port = port
        self.stats = stats
        self._tasks = tasks

    async def close(self) -> None:
        self._server.close()
        for t in list(self._tasks):
            t.cancel()
        with contextlib.suppress(Exception):
            await self._server.wait_closed()


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter, dec: Decision) -> None:
    try:
        while data := await src.read(65536):
            dec.bytes += len(data)
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with contextlib.suppress(Exception):
            dst.close()


def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())


async def start_listener(
    allow: list[str],
    port_range: tuple[int, int],
    *,
    bind: str = "0.0.0.0",  # noqa: S104 - the video-agents interface address in deployment
    allowed_ports: frozenset[int] = frozenset({443}),
    opener: Opener | None = None,
) -> EgressListener:
    """Open a listener on the first free port of `port_range` (inclusive)."""
    stats = ProxyStats()
    tasks: set[asyncio.Task[None]] = set()
    open_conn: Opener = opener or (lambda h, p: asyncio.open_connection(h, p))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task:
            tasks.add(task)
        try:
            line = await asyncio.wait_for(reader.readline(), 10)
            parts = line.decode("latin-1").split()
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):  # headers
                pass
            if len(parts) != 3 or parts[0].upper() != "CONNECT":
                stats.decisions.append(Decision(parts[1] if len(parts) > 1 else "?", 0, False))
                log.info(
                    "egress", host=parts[1] if len(parts) > 1 else "?", allowed=False, reason="not CONNECT"
                )
                _reply(writer, "405 Method Not Allowed")
                return
            host, _, port_s = parts[1].rpartition(":")
            port = int(port_s) if port_s.isdigit() else 0
            dec = Decision(host, port, host_allowed(host, allow) and port in allowed_ports)
            stats.decisions.append(dec)
            if not dec.allowed:
                log.info("egress", host=host, port=port, allowed=False)
                _reply(writer, "403 Forbidden")
                return
            try:
                up_r, up_w = await asyncio.wait_for(open_conn(host, port), 15)
            except (OSError, TimeoutError):
                _reply(writer, "502 Bad Gateway")
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(_pump(reader, up_w, dec), _pump(up_r, writer, dec))
            log.info("egress", host=host, port=port, allowed=True, bytes=dec.bytes)
        except (TimeoutError, ConnectionError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(Exception):
                writer.close()
            if task:
                tasks.discard(task)

    last: OSError | None = None
    for port in range(port_range[0], port_range[1] + 1):
        try:
            server = await asyncio.start_server(handle, bind, port)
        except OSError as exc:
            last = exc
            continue
        return EgressListener(server, port, stats, tasks)
    raise OSError(f"no free proxy port in {port_range}: {last}")
