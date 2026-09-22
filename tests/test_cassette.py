"""Record/replay cassette transport: (request key -> response), offline by default."""

import json
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.cassette import (
    RECORD_ENV,
    Cassette,
    CassetteMiss,
    CassetteTransport,
    Entry,
    cassette_client,
    request_key,
)


def _req(
    method: str = "GET", url: str = "https://api.example.org/q?b=2&a=1", **kw: object
) -> httpx2.Request:
    return httpx2.Request(method, url, **kw)  # pyright: ignore[reportArgumentType]


def test_key_ignores_query_param_order_and_headers():
    a = _req(url="https://x.org/q?a=1&b=2", headers={"Authorization": "Bearer one"})
    b = _req(url="https://x.org/q?b=2&a=1", headers={"Authorization": "Bearer two"})
    assert request_key(a) == request_key(b)


def test_key_ignores_json_key_order():
    a = _req("POST", "https://x.org/v1", json={"state": "s", "model": "m"})
    b = _req("POST", "https://x.org/v1", content=b'{"model": "m", "state": "s"}')
    assert request_key(a) == request_key(b)


def test_key_distinguishes_method_url_and_body():
    base = request_key(_req("POST", "https://x.org/v1", json={"a": 1}))
    assert base != request_key(_req("POST", "https://x.org/v1", json={"a": 2}))
    assert base != request_key(_req("POST", "https://x.org/v2", json={"a": 1}))
    assert base != request_key(_req("PUT", "https://x.org/v1", json={"a": 1}))


def test_key_is_readable_and_names_the_request():
    key = request_key(_req("POST", "https://x.org/v1?b=2&a=1", json={"a": 1}))
    assert key.startswith("POST https://x.org/v1?a=1&b=2 body:")


def test_key_ignores_secret_query_params():
    a = _req(url="https://x.org/q?q=agents&api_key=AAA")
    b = _req(url="https://x.org/q?q=agents&api_key=BBB")
    assert request_key(a) == request_key(b)


async def _upstream_ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"echo": request.url.path}, headers={"x-secret": "s"})


async def test_record_then_replay_offline(tmp_path: Path):
    path = tmp_path / "c.json"
    recorder = CassetteTransport(
        Cassette(path), record=True, upstream=httpx2.MockTransport(_upstream_ok)
    )
    async with httpx2.AsyncClient(transport=recorder) as client:
        live = await client.get("https://x.org/hello?token=T0P")
    assert live.json() == {"echo": "/hello"}

    replayer = CassetteTransport(Cassette(path), record=False)
    async with httpx2.AsyncClient(transport=replayer) as client:
        again = await client.get("https://x.org/hello?token=OTHER")
    assert again.status_code == 200
    assert again.json() == {"echo": "/hello"}


async def test_recorded_file_holds_no_secrets(tmp_path: Path):
    path = tmp_path / "c.json"
    recorder = CassetteTransport(
        Cassette(path), record=True, upstream=httpx2.MockTransport(_upstream_ok)
    )
    async with httpx2.AsyncClient(transport=recorder) as client:
        await client.get(
            "https://x.org/hello?token=T0P", headers={"Authorization": "Bearer SECRET"}
        )
    raw = path.read_text(encoding="utf-8")
    assert "T0P" not in raw
    assert "SECRET" not in raw
    assert "x-secret" not in raw


async def test_replay_miss_fails_loudly(tmp_path: Path):
    replayer = CassetteTransport(Cassette(tmp_path / "empty.json"), record=False)
    async with httpx2.AsyncClient(transport=replayer) as client:
        with pytest.raises(CassetteMiss, match=r"x\.org/nothing"):
            await client.get("https://x.org/nothing")


async def test_error_statuses_replay_too(tmp_path: Path):
    async def upstream(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(503, text="busy")

    path = tmp_path / "c.json"
    recorder = CassetteTransport(
        Cassette(path), record=True, upstream=httpx2.MockTransport(upstream)
    )
    async with httpx2.AsyncClient(transport=recorder) as client:
        await client.get("https://x.org/busy")
    async with httpx2.AsyncClient(
        transport=CassetteTransport(Cassette(path), record=False)
    ) as client:
        r = await client.get("https://x.org/busy")
    assert (r.status_code, r.text) == (503, "busy")


def test_cassette_file_is_deterministic(tmp_path: Path):
    a, b = Cassette(tmp_path / "a.json"), Cassette(tmp_path / "b.json")
    entries = [(k, Entry(status=200, content_type="text/plain", body=k)) for k in ("k2", "k1")]
    for key, entry in entries:
        a.put(key, entry)
    for key, entry in reversed(entries):
        b.put(key, entry)
    a.save()
    b.save()
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
    assert list(json.loads((tmp_path / "a.json").read_text())) == ["k1", "k2"]


def test_client_replays_unless_env_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(RECORD_ENV, raising=False)
    client = cassette_client(tmp_path / "c.json")
    assert isinstance(client, httpx2.AsyncClient)
    transport = client._transport  # pyright: ignore[reportPrivateUsage]
    assert isinstance(transport, CassetteTransport)
    assert transport.record is False


def test_client_records_only_with_env_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(RECORD_ENV, "1")
    transport = cassette_client(tmp_path / "c.json")._transport  # pyright: ignore[reportPrivateUsage]
    assert isinstance(transport, CassetteTransport)
    assert transport.record is True


def test_record_requires_upstream(tmp_path: Path):
    with pytest.raises(ValueError, match="upstream"):
        CassetteTransport(Cassette(tmp_path / "c.json"), record=True)
