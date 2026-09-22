"""Record/replay cassettes for every outbound HTTP call (decision 9).

Mechanism: a hand-rolled httpx2 transport over JSON files, not vcrpy — the adapters,
typesafe-sdk and pydantic-ai's OpenAI client all accept one injected httpx2 client, so
one typed transport covers every external call (vcrpy is untyped and patches globally).

Invariants:
- Replay is the default and never touches the network: a request with no recorded
  response raises CassetteMiss (a test fails loudly instead of going live).
- Recording happens only when a human sets JRP_CASSETTE_RECORD=1 (cassette_client).
- Key = "<METHOD> <URL with sorted query minus secret params> body:<16 hex of the
  JSON-canonical body's sha256>" — readable in diffs, collision-safe within one file.
  Headers are never part of the key and never stored, so API keys in Authorization /
  x-api-key headers cannot reach a cassette file.
- The file is sorted by key: re-recording the same traffic rewrites identical bytes.
"""

import json
import os
from pathlib import Path
from typing import Final, TypedDict, override
from urllib.parse import parse_qsl, urlencode

import httpx2
from pydantic import TypeAdapter

from .model import sha256_hex

RECORD_ENV: Final = "JRP_CASSETTE_RECORD"
# Query parameters that carry credentials in some APIs. Dropped from key and file.
SECRET_PARAMS: Final = frozenset({"api_key", "apikey", "key", "token", "access_token"})
DEFAULT_TIMEOUT: Final = 30.0


class CassetteMiss(LookupError):
    """Replay found no recorded response for a request."""


class Entry(TypedDict):
    status: int
    content_type: str
    body: str


def _redacted_url(url: httpx2.URL) -> str:
    params = sorted(
        (k, v) for k, v in parse_qsl(url.query.decode()) if k.lower() not in SECRET_PARAMS
    )
    base = str(url.copy_with(query=None))
    return f"{base}?{urlencode(params)}" if params else base


def _canonical_body(content: bytes) -> str:
    if not content:
        return ""
    try:
        return json.dumps(
            json.loads(content), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except ValueError:
        return content.decode("utf-8", errors="replace")


def request_key(request: httpx2.Request) -> str:
    body = _canonical_body(request.content)
    suffix = f" body:{sha256_hex(body)[:16]}" if body else ""
    return f"{request.method} {_redacted_url(request.url)}{suffix}"


_FILE: Final = TypeAdapter(dict[str, Entry])


class Cassette:
    """One JSON file: {request key: Entry}, validated on load."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: dict[str, Entry] = (
            _FILE.validate_json(path.read_bytes()) if path.exists() else {}
        )

    def get(self, key: str) -> Entry | None:
        return self._records.get(key)

    def put(self, key: str, response: Entry) -> None:
        self._records[key] = response

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = {k: self._records[k] for k in sorted(self._records)}
        self.path.write_text(
            json.dumps(ordered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )


class CassetteTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self, cassette: Cassette, *, record: bool, upstream: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        if record and upstream is None:
            raise ValueError("recording needs an upstream transport")
        self.cassette = cassette
        self.record = record
        self._upstream = upstream

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        key = request_key(request)
        if self.record and self._upstream is not None:
            live = await self._upstream.handle_async_request(request)
            await live.aread()
            entry = Entry(
                status=live.status_code,
                content_type=live.headers.get("content-type", ""),
                body=live.text,
            )
            await live.aclose()
            self.cassette.put(key, entry)
            self.cassette.save()
        else:
            found = self.cassette.get(key)
            if found is None:
                raise CassetteMiss(f"no recorded response for {key} in {self.cassette.path}")
            entry = found
        headers = {"content-type": entry["content_type"]} if entry["content_type"] else {}
        return httpx2.Response(
            entry["status"], headers=headers, text=entry["body"], request=request
        )


def cassette_client(path: Path, *, timeout: float = DEFAULT_TIMEOUT) -> httpx2.AsyncClient:
    """httpx2 client that replays `path`, or records into it when JRP_CASSETTE_RECORD=1."""
    record = os.environ.get(RECORD_ENV) == "1"
    upstream = httpx2.AsyncHTTPTransport() if record else None
    transport = CassetteTransport(Cassette(path), record=record, upstream=upstream)
    return httpx2.AsyncClient(transport=transport, timeout=timeout)
