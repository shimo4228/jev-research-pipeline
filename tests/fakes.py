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
    level; choice peaked at the first option. `answers` overrides per question name —
    `on_topic` covers every batch slot's `sN.on_topic`, `s1.on_topic` only that slot.
    """
    overrides = dict(answers or {})

    async def handle(request: httpx2.Request) -> httpx2.Response:
        if status != 200:
            return httpx2.Response(status, json={"error": {"message": "synthetic failure"}})
        body = json.loads(request.content)
        out: dict[str, object] = {}
        for name, q in body["questions"].items():
            # A batched request names a field `sN.<field>`; it answers like `<field>`
            # unless the slot is overridden on its own.
            given = overrides.get(name, overrides.get(name.rsplit(".", 1)[-1]))
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


E2E_ABSTRACT = (
    # Long enough to be an abstract: screening routes anything shorter to "incomplete".
    "We decompose research judgment into narrow typed questions. "
    "Fitted thresholds on author labels raise precision by twelve points. "
    "The pipeline writes one report per research line each day. "
    "We compare the decomposition against a single broad prompt on the same corpus, "
    "and report agreement with the author's own labels for every question in the set."
)


PROPOSALS = json.dumps(
    {
        "questions": [
            {
                "title": "記憶機構の差はどこで効くのか",
                "brief": "下流の精度差を決める条件を切り分ける。",
            }
        ]
    }
)


ARXIV_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <channel>
    <title>cs.AI</title>
    <item>
      <title>Narrow Questions Beat Broad Prompts</title>
      <link>https://arxiv.org/abs/2609.09876v1</link>
      <description>arXiv:2609.09876v1 Announce Type: new
{abstract}</description>
    </item>
    <item>
      <title>A Replaced Paper</title>
      <link>https://arxiv.org/abs/2609.00001v2</link>
      <description>arXiv:2609.00001v2 Announce Type: replace
{abstract}</description>
    </item>
  </channel>
</rss>
"""

OPENALEX_WORKS = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.48550/arXiv.2609.00002",
            "title": "Citing Work",
            "publication_date": "2026-09-20",
            "primary_topic": {"id": "T10017", "display_name": "Agent memory"},
        }
    ]
}

S2_RECOMMENDATIONS = {
    "recommendedPapers": [
        {
            "title": "Recommended Work",
            "url": "https://www.semanticscholar.org/paper/abc",
            "abstract": "A recommended abstract about narrow typed questions and labels.",
            "externalIds": {"ArXiv": "2609.00003"},
            "publicationDate": "2026-09-19",
        }
    ]
}


def _keyword_response(host: str | None) -> httpx2.Response:
    """The original keyword net's upstreams (and the 404 for anything unexpected)."""
    if host == "export.arxiv.org":
        atom = ARXIV_ATOM.replace(
            "We decompose judgment into narrow questions.\n  Fitted weights raise accuracy.",
            E2E_ABSTRACT,
        )
        return httpx2.Response(200, text=atom, headers={"content-type": "application/atom+xml"})
    if host == "huggingface.co":
        return httpx2.Response(200, json=[])
    if host == "api.github.com":
        return httpx2.Response(
            200, json={"total_count": 0, "incomplete_results": False, "items": []}
        )
    return httpx2.Response(404, json={"error": f"unexpected host {host}"})


def _discovery_response(request: httpx2.Request, host: str | None) -> httpx2.Response | None:
    """The nets that are not keyword search: arXiv listings, HF daily, S2, OpenAlex."""
    if host == "rss.arxiv.org":
        return httpx2.Response(
            200,
            text=ARXIV_RSS.format(abstract=E2E_ABSTRACT),
            headers={"content-type": "application/rss+xml"},
        )
    if host == "api.semanticscholar.org":
        return httpx2.Response(200, json=S2_RECOMMENDATIONS)
    if host == "api.openalex.org":
        return httpx2.Response(
            200,
            json=OPENALEX_WORKS,
            headers={"x-ratelimit-credits-used": "1", "x-ratelimit-remaining": "988"},
        )
    if host == "huggingface.co" and request.url.path == "/api/daily_papers":
        return httpx2.Response(
            200,
            json=[
                {
                    "paper": {
                        "id": "2609.00004",
                        "title": "Daily Paper",
                        "summary": E2E_ABSTRACT,
                        "publishedAt": "2026-09-22T00:00:00.000Z",
                    }
                }
            ],
        )
    return None


def fake_world() -> Handler:
    """Every upstream of one line-run, routed by host (end-to-end test only).

    The Noul answers are deliberately confident: the screening routes a source to Review
    below certainty 0.9, so the default 0.8 would send every source to the author and the
    run would produce no claims at all."""
    jev = fake_jev(
        {
            "prompt_injection": 0.05,
            "unsupported_statement": 0.05,
            "exceeds_claims": 0.05,
            "on_topic": 0.97,
            "method_transferable": 0.97,
            "evidence_compatible": 0.97,
            "contains_evidence": 0.97,
            "checkable": 0.97,
            "same_source": 0.03,
            "contradiction": 0.03,
            "bridges_line": 0.97,
            "open_for_line": 0.97,
            "answerable_by_evidence": 0.97,
        }
    )

    async def handle(request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        if host == "api.typesafe.ai":
            return await jev(request)
        discovered = _discovery_response(request, host)
        if discovered is not None:
            return discovered
        if host == "dashscope-intl.aliyuncs.com":
            body = json.loads(request.content)
            asked = json.dumps(body, ensure_ascii=False)
            if body["model"] != "deepseek-v4.1-flash":
                content = "狭い型付き質問への分解で判定が安定する [1]。"
            elif "問い" in asked and "queries" not in asked:
                content = PROPOSALS
            else:
                content = json.dumps(
                    {"queries": ["narrow typed questions", "author label thresholds"]}
                )
            return await fake_qwen(content)(request)
        return _keyword_response(host)

    return handle
