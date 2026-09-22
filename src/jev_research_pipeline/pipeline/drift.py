"""Weekly drift job (decision 9): replay recorded Jev inputs against the live model.

Each recorded /v1/systemone request body (kept in live cassettes; headers never are) is
sent again, and every question's answer distribution is compared with the recording.
The body pins the model version, so a delta means the pinned model changed behaviour.
Live calls happen only through the CLI when JRP_DRIFT_LIVE=1 is set by a human.
"""

from pathlib import Path
from typing import Final

import httpx2
from pydantic import JsonValue, TypeAdapter

from jev_research_pipeline.cassette import Cassette
from jev_research_pipeline.model.jsonld import Value

LIVE_ENV: Final = "JRP_DRIFT_LIVE"
SYSTEM_ONE: Final = "https://api.typesafe.ai/v1/systemone"


class DriftRow(Value):
    cassette: str
    question: str
    delta: float
    """Largest absolute probability change over the answer's outcomes."""


def _probs(answer: JsonValue) -> dict[str, float]:
    if not isinstance(answer, dict):
        return {}
    noul = answer.get("noul")
    if answer.get("type") == "noul" and isinstance(noul, float | int):
        return {"yes": float(noul)}
    probs = answer.get("probabilities")
    if isinstance(probs, dict):
        return {str(k): float(v) for k, v in probs.items() if isinstance(v, float | int)}
    return {}


_BODY: Final = TypeAdapter(dict[str, JsonValue])


def _answers(body: str) -> dict[str, JsonValue]:
    answers = _BODY.validate_json(body).get("answers")
    return answers if isinstance(answers, dict) else {}


async def drift(paths: list[Path], client: httpx2.AsyncClient, *, api_key: str) -> list[DriftRow]:
    rows, _ = await drift_with_failures(paths, client, api_key=api_key)
    return rows


async def drift_with_failures(
    paths: list[Path], client: httpx2.AsyncClient, *, api_key: str
) -> tuple[list[DriftRow], int]:
    """(rows, replays that got no 200). All-failed is a failure, never "no drift"."""
    rows: list[DriftRow] = []
    failed = 0
    for path in paths:
        for key, entry in Cassette(path).entries().items():
            body = entry.get("request_body")
            if not key.startswith(f"POST {SYSTEM_ONE}") or body is None or entry["status"] != 200:
                continue
            live = await client.post(
                SYSTEM_ONE,
                content=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            if live.status_code != 200:
                failed += 1
                continue
            recorded, now = _answers(entry["body"]), _answers(live.text)
            for question, answer in recorded.items():
                old, new = _probs(answer), _probs(now.get(question))
                delta = max((abs(p - new.get(k, 0.0)) for k, p in old.items()), default=0.0)
                rows.append(DriftRow(cassette=path.name, question=question, delta=round(delta, 6)))
    return rows, failed


def drift_table(rows: list[DriftRow]) -> str:
    lines = ["| cassette | question | max Δp |", "|---|---|---|"]
    lines += [
        f"| {r.cassette} | {r.question} | {r.delta:.3f} |"
        for r in sorted(rows, key=lambda r: -r.delta)
    ]
    return "\n".join(lines) + "\n"
