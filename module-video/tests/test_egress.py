import asyncio

import pytest

from mvideo.net.egress_proxy import host_allowed, start_listener


def test_allowlist_rules() -> None:
    allow = ["api.anthropic.com", "*.example.org"]
    assert host_allowed("api.anthropic.com", allow)
    assert host_allowed("A.Example.org", allow)
    assert not host_allowed("example.org", allow)  # the suffix rule needs a subdomain
    assert not host_allowed("evil-api.anthropic.com.attacker.net", allow)
    assert not host_allowed("github.com", allow)


async def _connect(port: int, target: str) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await w.drain()
    return await r.readuntil(b"\r\n\r\n"), r, w


async def test_connect_allowed_tunnels_and_denied_is_refused_and_counted() -> None:
    async def echo(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        w.write(b"echo:" + await r.read(100))
        await w.drain()
        w.close()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    uport = upstream.sockets[0].getsockname()[1]

    async def opener(host: str, port: int):  # type: ignore[no-untyped-def]
        assert host == "api.anthropic.com"
        return await asyncio.open_connection("127.0.0.1", uport)

    lst = await start_listener(
        ["api.anthropic.com"],
        (38200, 38210),
        bind="127.0.0.1",
        allowed_ports=frozenset({443, 8443}),
        opener=opener,
    )
    try:
        head, r, w = await _connect(lst.port, "api.anthropic.com:8443")
        assert head.startswith(b"HTTP/1.1 200")
        w.write(b"hi")
        await w.drain()
        assert await r.read(100) == b"echo:hi"
        w.close()

        head, _, w2 = await _connect(lst.port, "evil.example.net:443")
        assert head.startswith(b"HTTP/1.1 403")
        head, _, w3 = await _connect(lst.port, "api.anthropic.com:22")  # wrong port
        assert head.startswith(b"HTTP/1.1 403")
        r4, w4 = await asyncio.open_connection("127.0.0.1", lst.port)  # plain HTTP
        w4.write(b"GET http://api.anthropic.com/ HTTP/1.1\r\n\r\n")
        assert (await r4.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 405")
        await asyncio.sleep(0.05)
        assert lst.stats.denied == 3 and lst.stats.allowed == 1
        for x in (w2, w3, w4):
            x.close()
    finally:
        await lst.close()
        upstream.close()


async def test_second_listener_takes_next_free_port() -> None:
    a = await start_listener([], (38220, 38221), bind="127.0.0.1")
    b = await start_listener([], (38220, 38221), bind="127.0.0.1")
    try:
        assert {a.port, b.port} == {38220, 38221}
        with pytest.raises(OSError):
            await start_listener([], (38220, 38221), bind="127.0.0.1")
    finally:
        await a.close()
        await b.close()
