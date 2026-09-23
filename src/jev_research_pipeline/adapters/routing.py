"""The run's HTTP transport: httpx2 for everything, except hosts that refuse httpx2.

export.arxiv.org answers 406 to httpx2 on every query its cache does not already hold, and
200 to urllib, curl and a hand-written TLS request with the same URL and headers (measured
2026-09-23: same path bytes, same header names and casing, with and without keep-alive,
HTTP/1.1 and 2, a default SSL context passed to httpx2 — only httpx2 is refused; cached
queries answer 200 to anyone, which is why it looked intermittent). The difference is
below the request line and headers and was not isolated further. Requests to such a host
go through urllib in a worker thread; the adapter, its pacing and the cassettes are
unchanged (tests inject their own client and never reach this transport).
"""

import asyncio
import urllib.error
import urllib.request
from typing import Final, override

import httpx2

URLLIB_HOSTS: Final = frozenset({"export.arxiv.org"})


class UrllibTransport(httpx2.AsyncBaseTransport):
    """One request per call through urllib (no pooling, like arXiv's one-connection ToU)."""

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def _send(self, request: httpx2.Request) -> tuple[int, dict[str, str], bytes]:
        if request.url.scheme != "https":
            raise httpx2.UnsupportedProtocol(f"refusing {request.url.scheme}")
        req = urllib.request.Request(
            str(request.url),
            data=request.content or None,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            method=request.method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                return resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers.items()), e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise httpx2.ConnectError(str(e)) from e

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        status, headers, body = await asyncio.to_thread(self._send, request)
        # The body is already decoded bytes as urllib returned them.
        headers.pop("Content-Encoding", None)
        headers.pop("content-encoding", None)
        return httpx2.Response(status, headers=headers, content=body, request=request)


class HostRoutedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, *, timeout: float, fallback: httpx2.AsyncBaseTransport) -> None:
        self._urllib = UrllibTransport(timeout=timeout)
        self._fallback = fallback

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host in URLLIB_HOSTS:
            return await self._urllib.handle_async_request(request)
        return await self._fallback.handle_async_request(request)

    @override
    async def aclose(self) -> None:
        await self._fallback.aclose()


def run_client(*, timeout: float) -> httpx2.AsyncClient:
    """The shared client of a live run (cli): httpx2, with URLLIB_HOSTS routed around it."""
    transport = HostRoutedTransport(timeout=timeout, fallback=httpx2.AsyncHTTPTransport())
    return httpx2.AsyncClient(timeout=timeout, transport=transport)
