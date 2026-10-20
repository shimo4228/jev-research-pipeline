"""Asking Jev again over frozen states: the noise floor (`jrp eval gate jitter`) and an ask
candidate (a reworded screen, evals.gate_score). Research report 2026-10-20-sx-eval-loop.

Both send a screening state rebuilt at freeze time (its sha256 matched the stored Judgment's,
evals.gate_set) through a plain JevClient, never the run's StoredJev, so nothing is answered
from the store. jitter asks today's ASK and compares the route of the stored answer with the
route of the fresh one, under today's thresholds: the share of routes that flip is the floor
an ask candidate's changes are read against (the inventory's last measurement: 2-3 of 40,
2026-10-01). Requests go one at a time up to `max_questions` Jev questions; the estimated
price is questions x JRP_JEV_USD_PER_QUESTION (pipeline.costs; unset = 0, said so).
"""

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import httpx2
from pydantic import AwareDatetime

from jev_research_pipeline.jev import JevClient, JevFailure, Judged, judged_of, question_screening
from jev_research_pipeline.jev.core import Ask, JevState
from jev_research_pipeline.model import Judgment
from jev_research_pipeline.pipeline.costs import Budget
from jev_research_pipeline.pipeline.metrics import append_row, lines

from .gate_set import GateSet
from .stats import wilson

KEY_ENV: Final = "TYPESAFE_API_KEY"
JITTER_FILE: Final = "jitter.jsonl"
DEFAULT_N: Final = 40
DEFAULT_MAX_QUESTIONS: Final = 400
HTTP_TIMEOUT_S: Final = 30.0
"""The HTTP client's timeout: above jev.core.JEV_TIMEOUT_S, which bounds each request."""
QUESTIONS_PER_ASK: Final = len(question_screening.Answers.model_fields)


@dataclass(frozen=True)
class Reasked:
    """The fresh answers for some frozen states, and what asking them cost."""

    answers: Mapping[str, Judged[question_screening.Answers]]
    """Stored Judgment @id → the fresh answer over the same state."""
    failed: int = 0
    stopped: bool = False
    """The question budget ran out before every state was asked."""
    questions: int = 0
    usd: float = 0.0
    price_known: bool = False


async def reask(
    ask: Ask[question_screening.Answers],
    states: Mapping[str, tuple[tuple[str, ...], JevState]],
    jids: Sequence[str],
    env: Mapping[str, str],
    *,
    http: httpx2.AsyncClient,
    now: AwareDatetime,
    max_questions: int,
) -> Reasked | None:
    """Ask `ask` over the states of `jids`; None without TYPESAFE_API_KEY."""
    key = env.get(KEY_ENV)
    if not key:
        return None
    client = JevClient(http, api_key=key)
    budget = Budget(env)
    answers: dict[str, Judged[question_screening.Answers]] = {}
    failed = 0
    stopped = False
    for jid in jids:
        if jid not in states:
            continue
        if client.questions_asked + QUESTIONS_PER_ASK > max_questions:
            stopped = True
            break
        subjects, state = states[jid]
        result = await client.judge(ask, subjects, state, now=now)
        if isinstance(result, JevFailure):
            failed += 1
        else:
            answers[jid] = result
    return Reasked(
        answers=answers,
        failed=failed,
        stopped=stopped,
        questions=client.questions_asked,
        usd=client.questions_asked * budget.jev_price,
        price_known=budget.jev_price_known,
    )


@dataclass(frozen=True)
class Floor:
    """Routes that flipped when the same state was asked again."""

    judged: int
    flips: int
    mean_abs_dw: float = 0.0
    max_abs_dw: float = 0.0
    runs: int = 0

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.flips, self.judged) if self.judged else None


@dataclass(frozen=True)
class JitterResult:
    asked: int
    reasked: Reasked | None
    floor: Floor
    rows: list[dict[str, object]] = field(default_factory=list[dict[str, object]])


def _sample(gs: GateSet, states: Mapping[str, object], n: int, seed: str) -> list[str]:
    screened = sorted({jid for p in gs.pairs for jid in p.screening if jid in states})
    return random.Random(seed).sample(screened, min(n, len(screened)))


def _judged(j: Judgment) -> Judged[question_screening.Answers] | None:
    return judged_of(question_screening.ASK, j)


async def jitter(
    gs: GateSet,
    env: Mapping[str, str],
    *,
    http: httpx2.AsyncClient,
    now: AwareDatetime,
    n: int = DEFAULT_N,
    max_questions: int = DEFAULT_MAX_QUESTIONS,
) -> JitterResult:
    """Ask n sampled screening states again (seeded by the set's name and the run's day) and
    append one row per answer to <set>/jitter.jsonl."""
    states = gs.states()
    jids = _sample(gs, states, n, f"{gs.manifest.name}/{now.date().isoformat()}")
    got = await reask(
        question_screening.ASK, states, jids, env, http=http, now=now, max_questions=max_questions
    )
    if got is None:
        return JitterResult(asked=len(jids), reasked=None, floor=floor(gs.root))
    path = gs.root / JITTER_FILE
    rows: list[dict[str, object]] = []
    for jid, fresh in got.answers.items():
        old = _judged(gs.judgments[jid])
        if old is None or fresh.judgment.state_sha256 != gs.judgments[jid].state_sha256:
            continue
        row: dict[str, object] = {
            "at": now.isoformat(),
            "judgment": jid,
            "route_old": question_screening.judged_route(old),
            "route_new": question_screening.judged_route(fresh),
            "w_old": question_screening.weighted(old),
            "w_new": question_screening.weighted(fresh),
            "on_topic_old": old.output.on_topic,
            "on_topic_new": fresh.output.on_topic,
        }
        append_row(path, row)  # pyright: ignore[reportArgumentType]
        rows.append(row)
    return JitterResult(asked=len(jids), reasked=got, floor=floor(gs.root), rows=rows)


def floor(root: Path) -> Floor:
    """<set>/jitter.jsonl read as one floor, one row per stored Judgment (its latest), so a
    state asked on two days counts once."""
    latest: dict[str, tuple[float, bool, str]] = {}
    for raw in lines(root / JITTER_FILE):
        try:
            row = json.loads(raw)
            dw = abs(float(row["w_new"]) - float(row["w_old"]))
            latest[str(row["judgment"])] = (
                dw,
                row["route_old"] != row["route_new"],
                str(row["at"])[:10],
            )
        except (ValueError, KeyError, TypeError):
            continue
    dws = [dw for dw, _, _ in latest.values()]
    judged = len(latest)
    flips = sum(1 for _, f, _ in latest.values() if f)
    days = {d for _, _, d in latest.values()}
    return Floor(
        judged=judged,
        flips=flips,
        mean_abs_dw=sum(dws) / len(dws) if dws else 0.0,
        max_abs_dw=max(dws, default=0.0),
        runs=len(days),
    )
