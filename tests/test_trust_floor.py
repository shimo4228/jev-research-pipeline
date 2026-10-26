"""The trust floor per question (source_trust.floor): a `trust: personal` question also
takes a named author's own writing; every other question keeps min_trust. The stored
Decision stays question-free.

LineRun._safe_sources runs on a LineRun that holds only what the pass reads (questions,
ctx, lang, state); its Jev requests go through the client the run uses, over a fake Jev.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2
import pytest

from jev_research_pipeline.jev import JevClient, source_trust
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.jev.core import Ask, JevState
from jev_research_pipeline.model import Question, SourceItem
from jev_research_pipeline.pipeline.run import (
    LineRun,
    _State,  # pyright: ignore[reportPrivateUsage]
)

from . import builders as b
from .fakes import Distribution, NoulValue, fake_jev

TEXT = "A named author's account of agent memory with a measured result. " * 5
PERSONAL: Distribution = (0.0, 1.0, 0.0, 0.0)
ANONYMOUS: Distribution = (1.0, 0.0, 0.0, 0.0)
REPORT: Distribution = (0.0, 0.0, 1.0, 0.0)
OFFLINE = "offline"
"""The Jev key of a client that only reaches the fake Jev."""


def test_floor_by_level():
    assert source_trust.floor("report") == 0.5
    assert source_trust.floor("personal") == pytest.approx(1 / 6)
    stricter = (
        source_trust.THRESHOLDS[0],
        source_trust.THRESHOLDS[1].model_copy(update={"value": 0.9}),
    )
    assert source_trust.floor("personal", stricter) == 0.5  # never above a report question's


def _source(i: int) -> SourceItem:
    return SourceItem.new(
        line=b.LINE_IRI,
        adapter="feed",
        url=f"https://example.org/post/{i}",
        title=f"Post {i}",
        text=TEXT,
        fetched_at=b.T0,
    )


def _run(questions: list[Question], trust: Sequence[Distribution]) -> LineRun:
    run = object.__new__(LineRun)
    run.questions = questions
    run.ctx = LineContext(line=b.line(), vocabulary=("agent memory",))
    run.lang = "ja"
    run.st = _State()
    answers: Mapping[str, NoulValue | Distribution] = {
        "contains_evidence": 0.9,
        "prompt_injection": 0.05,
        **{f"s{i}.trust": d for i, d in enumerate(trust)},
    }

    async def batched(ask: Ask[Any], items: Sequence[tuple[tuple[str, ...], JevState]]) -> Any:
        transport = httpx2.MockTransport(fake_jev(answers))
        async with httpx2.AsyncClient(transport=transport) as http:
            return await JevClient(http, api_key=OFFLINE).judge_batch(
                ask, list(items), subject="source", now=b.T0
            )

    run._batched = batched  # pyright: ignore[reportPrivateUsage]
    return run


async def test_a_personal_page_reaches_only_the_personal_question():
    report_q = b.question()
    personal_q = report_q.model_copy(update={"id": "q-personal", "trust_level": "personal"})
    sources = [_source(i) for i in range(3)]
    run = _run([report_q, personal_q], [PERSONAL, ANONYMOUS, REPORT])
    passing = {s.id: [0, 1] for s in sources}

    kept, narrowed = await run._safe_sources(sources, passing)  # pyright: ignore[reportPrivateUsage]

    blog, ad, paper = sources
    assert [s.id for s in kept] == [blog.id, paper.id]
    assert narrowed == {blog.id: [1], paper.id: [0, 1]}  # the anonymous page reaches none
    # the stored trust Decisions stay question-free: the blog is still a reject at min_trust
    trust = {d.subjects[0]: d.outcome for d in run.st.decisions if d.function == "source_trust"}
    assert trust == {blog.id: "reject", ad.id: "reject", paper.id: "accept"}
    assert run.st.notes == ["個人の記述として 1 件を通した (trust: personal の問いだけ)"]


async def test_without_a_personal_question_nothing_changes():
    sources = [_source(i) for i in range(2)]
    run = _run([b.question()], [PERSONAL, REPORT])
    kept, narrowed = await run._safe_sources(sources, {s.id: [0] for s in sources})  # pyright: ignore[reportPrivateUsage]
    assert [s.id for s in kept] == [sources[1].id]
    assert narrowed == {sources[1].id: [0]}
    assert run.st.notes == []
