"""Fake upstreams used only to synthesize cassettes (JRP_CASSETTE_SYNTHETIC=1).

Response shapes follow the providers' wire formats as read from the SDK sources
(typesafe_sdk/_schemas/models.py) and the providers' API docs, as-of 2026-09-22.
"""

import json
from collections.abc import Mapping

import httpx2

from .conftest import Handler

type NoulValue = float
type Distribution = tuple[float, ...]


def fake_jev(
    answers: Mapping[str, NoulValue | Distribution | Mapping[str, float]] | None = None,
    *,
    model: str = "jev-1.13.0",
    status: int = 200,
) -> Handler:
    """TypeSafe /v1/systemone. Unlisted questions get: noul 0.8; score peaked at the top
    level; choice peaked at the first option. `answers` overrides per question name."""
    overrides = dict(answers or {})

    async def handle(request: httpx2.Request) -> httpx2.Response:
        if status != 200:
            return httpx2.Response(status, json={"error": {"message": "synthetic failure"}})
        body = json.loads(request.content)
        out: dict[str, object] = {}
        for name, q in body["questions"].items():
            given = overrides.get(name)
            if q["type"] == "noul":
                p = given if isinstance(given, float) else 0.8
                out[name] = {"type": "noul", "noul": p}
            elif q["type"] == "score":
                n = len(q["criteria"])
                dist = (
                    given
                    if isinstance(given, tuple)
                    else tuple(1.0 if i == n - 1 else 0.0 for i in range(n))
                )
                out[name] = {
                    "type": "score",
                    "score": sum(i * p for i, p in enumerate(dist)),
                    "confidence": max(dist),
                    "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                    "probabilities": {str(i): p for i, p in enumerate(dist)},
                }
            else:
                labels = list(q["criteria"])
                probs = (
                    dict(given)
                    if isinstance(given, Mapping)
                    else {label: (1.0 if i == 0 else 0.0) for i, label in enumerate(labels)}
                )
                out[name] = {
                    "type": "choice",
                    "choice": max(probs, key=lambda k: probs[k]),
                    "confidence": max(probs.values()),
                    "probabilities": probs,
                }
        return httpx2.Response(
            200,
            json={
                "model": model,
                "usage": {"input_tokens": 100, "output_tokens": 5},
                "answers": out,
            },
        )

    return handle


ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>arXiv Query</title>
  <entry>
    <id>http://arxiv.org/abs/2609.01234v1</id>
    <published>2026-09-20T17:59:59Z</published>
    <updated>2026-09-20T17:59:59Z</updated>
    <title>Narrow Questions Beat
  Broad Prompts</title>
    <summary>  We decompose judgment into narrow questions.
  Fitted weights raise accuracy.  </summary>
    <link href="https://arxiv.org/abs/2609.01234v1" rel="alternate" type="text/html"/>
    <link href="https://arxiv.org/pdf/2609.01234v1" rel="related" type="application/pdf" title="pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2609.05678v2</id>
    <published>2026-09-19T10:00:00Z</published>
    <title>Agent Memory Layers</title>
    <summary>Episode logs feed a knowledge store.</summary>
    <link href="https://arxiv.org/abs/2609.05678v2" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

HF_SEARCH = [
    {
        "paper": {
            "id": "2609.01234",
            "title": "Narrow Questions Beat Broad Prompts",
            "summary": "We decompose judgment into narrow questions.",
            "publishedAt": "2026-09-20T17:59:59.000Z",
            "upvotes": 12,
        },
        "title": "Narrow Questions Beat Broad Prompts",
        "publishedAt": "2026-09-21T02:00:00.000Z",
    }
]

GITHUB_SEARCH: dict[str, object] = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "full_name": "someone/agent-memory",
            "html_url": "https://github.com/someone/agent-memory",
            "description": "Episode log to knowledge store for LLM agents.",
            "topics": ["llm", "agents"],
            "created_at": "2026-08-01T00:00:00Z",
            "pushed_at": "2026-09-20T00:00:00Z",
            "stargazers_count": 120,
        },
        {
            "full_name": "someone/empty",
            "html_url": "https://github.com/someone/empty",
            "description": None,
            "topics": [],
            "created_at": "2026-08-02T00:00:00Z",
        },
    ],
}

TAVILY_SEARCH = {
    "query": "agent memory",
    "results": [
        {
            "title": "Designing agent memory",
            "url": "https://example.org/agent-memory",
            "content": "A practitioner write-up on episodic memory for agents.",
            "score": 0.91,
            "published_date": "2026-09-18",
        },
        {
            "title": "Undated page",
            "url": "https://example.org/undated",
            "content": "No date on this one.",
            "score": 0.5,
        },
    ],
}


def fake_json(
    payload: object, *, status: int = 200, content_type: str = "application/json"
) -> Handler:
    async def handle(request: httpx2.Request) -> httpx2.Response:
        if content_type == "application/json":
            return httpx2.Response(status, json=payload)
        return httpx2.Response(status, text=str(payload), headers={"content-type": content_type})

    return handle


def fake_qwen(*contents: str | None, status: int = 200) -> Handler:
    """DashScope OpenAI-compatible /chat/completions. Returns `contents` in order, one per
    request (retries and rewrites are further requests); None = an HTTP error `status`."""
    queue = list(contents)

    async def handle(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        content = queue.pop(0) if queue else None
        if content is None:
            return httpx2.Response(
                status if status != 200 else 500, json={"error": {"message": "synthetic"}}
            )
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-synthetic",
                "object": "chat.completion",
                "created": 1790000000,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
            },
        )

    return handle
