"""The nine Jev functions (packet judgment map): bundles, states, rules — cassette-backed."""

from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from jev_research_pipeline.jev import (
    JevClient,
    JevFailure,
    ScoreQ,
    claim_detection,
    novelty,
    query_selection,
    relevance_triage,
    report_ordering,
    rubric_claim,
    rubric_report,
    source_support,
    source_trust,
)
from jev_research_pipeline.jev.context import EXCERPT_CHARS, LineContext, source_state
from jev_research_pipeline.model import (
    SUBJECT_KINDS,
    Claim,
    Judgment,
    QueryCandidate,
    SourceItem,
    Unit,
)
from jev_research_pipeline.store import ClaimIndex, GraphStore

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev

MODULES: list[ModuleType] = [
    query_selection,
    relevance_triage,
    claim_detection,
    novelty,
    source_support,
    source_trust,
    report_ordering,
    rubric_claim,
    rubric_report,
]
CTX = LineContext(line=b.line(), vocabulary=("agent memory", "narrow questions"))


def _jev(
    cassette: ClientFactory, answers: Mapping[str, object] | None = None, **kw: object
) -> JevClient:
    return JevClient(cassette(fake_jev(answers, **kw)), api_key="replay")  # pyright: ignore[reportArgumentType]


# --- every module --------------------------------------------------------------------------


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_bundle_is_the_function_of_its_module(module: ModuleType):
    assert module.BUNDLE.function == module.__name__.rsplit(".", 1)[-1]
    assert module.BUNDLE.function in SUBJECT_KINDS


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_score_levels_are_concrete_sentences(module: ModuleType):
    for q in module.BUNDLE.questions:
        if isinstance(q, ScoreQ):
            for level in q.levels:
                # A concrete situation reads as a sentence, not a one-word degree ("high").
                assert len(level.description.split()) >= 5, (q.key, level.key)


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_threshold_names_are_unique(module: ModuleType):
    names = [t.name for t in module.THRESHOLDS]
    assert len(names) == len(set(names))


def test_all_nine_functions_have_a_module():
    assert {m.BUNDLE.function for m in MODULES} == set(SUBJECT_KINDS)


def test_state_excerpts_long_source_text():
    long = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/3",
        title="t",
        text="x" * 5000,
        fetched_at=b.T0,
    )
    ex = source_state(long)["excerpt"]
    assert isinstance(ex, str) and len(ex) <= EXCERPT_CHARS + 2


# --- query_selection: top-k over candidates ----------------------------------------------


def _query(text: str) -> QueryCandidate:
    return QueryCandidate.new(line=b.LINE_IRI, adapter="arxiv", text=text)


async def test_query_selection_keeps_top_k_above_floor(cassette: ClientFactory):
    queries = [_query(f"q{i}") for i in range(5)]
    dists = {
        "q0": (0.0, 0.0, 0.0, 1.0),
        "q1": (0.0, 0.0, 1.0, 0.0),
        "q2": (0.0, 0.0, 0.5, 0.5),
        "q3": (0.0, 0.0, 1.0, 0.0),
        "q4": (1.0, 0.0, 0.0, 0.0),
    }
    results: list[Judgment | JevFailure] = []
    for q in queries:
        jev = _jev(cassette, {"expected_yield": dists[q.text]})
        results.append(await query_selection.judge(jev, CTX, q, now=b.T0))
    decisions = query_selection.rank(results)
    kept = [q.text for q, d in zip(queries, decisions, strict=True) if d.outcome == "accept"]
    # q0 (1.0), q2 (0.83), then q1/q3 tie at 0.67 broken by @id; q4 (0.0) is below the floor.
    tie_winner = min((queries[1], queries[3]), key=lambda q: q.id).text
    assert set(kept) == {"q0", "q2", tie_winner}
    assert all(d.thresholds == query_selection.THRESHOLDS for d in decisions)


def test_query_selection_unjudged_is_never_kept():
    failure = JevFailure(
        function="query_selection", subjects=(_query("x").id,), reason="timeout", detail=""
    )
    (d,) = query_selection.rank([failure])
    assert d.outcome == "unjudged"


# --- relevance_triage ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answers", "outcome"),
    [
        ({"relevant": 0.9, "contains_evidence": 0.8, "prompt_injection": 0.1}, "accept"),
        ({"relevant": 0.9, "contains_evidence": 0.8, "prompt_injection": 0.7}, "reject"),
        ({"relevant": 0.2, "contains_evidence": 0.8, "prompt_injection": 0.1}, "reject"),
    ],
    ids=["clean", "injection", "off_topic"],
)
async def test_relevance_triage_rule(
    cassette: ClientFactory, answers: dict[str, object], outcome: str
):
    result = await relevance_triage.judge(_jev(cassette, answers), CTX, b.source(), now=b.T0)
    assert relevance_triage.decision(result).outcome == outcome


async def test_relevance_triage_failure_is_unjudged(cassette: ClientFactory):
    result = await relevance_triage.judge(_jev(cassette, status=400), CTX, b.source(), now=b.T0)
    assert relevance_triage.decision(result).outcome == "unjudged"


# --- claim_detection -----------------------------------------------------------------------


async def test_claim_detection_accepts_checkable_relevant_unit(cassette: ClientFactory):
    result = await claim_detection.judge(_jev(cassette), CTX, b.unit(), b.source(), now=b.T0)
    d = claim_detection.decision(result)
    assert (d.outcome, d.subjects) == ("accept", (b.unit().id,))


async def test_claim_detection_rejects_non_claim(cassette: ClientFactory):
    result = await claim_detection.judge(
        _jev(cassette, {"checkable_claim": 0.1}), CTX, b.unit(), b.source(), now=b.T0
    )
    assert claim_detection.decision(result).outcome == "reject"


# --- novelty: code pre-pass, then pairs ----------------------------------------------------


def _claim(text: str, url: str) -> Claim:
    src = SourceItem.new(
        line=b.LINE_IRI, adapter="arxiv", url=url, title="t", text=text, fetched_at=b.T0
    )
    return Claim.from_unit(
        Unit.cut(src, start=0, end=len(text), granularity="sentence"), line=b.LINE_IRI
    )


def test_novelty_prepass_excludes_self_and_caps_k(tmp_path: Path):
    stored = [
        _claim(f"Agent memory result number {i}.", f"https://arxiv.org/abs/{i}") for i in range(8)
    ]
    part = GraphStore(tmp_path).line("akc")
    part.put(stored)
    index = ClaimIndex.rebuild(tmp_path / "i.sqlite", part)
    pairs = novelty.candidate_pairs(index, stored[0])
    assert stored[0].id not in pairs
    assert len(pairs) == 5


async def test_novelty_same_claim_pair_marks_duplicate(cassette: ClientFactory):
    new, old = (
        _claim("A says B.", "https://arxiv.org/abs/n"),
        _claim("A states B.", "https://arxiv.org/abs/o"),
    )
    result = await novelty.judge(_jev(cassette, {"relation": (0.0, 0.1, 0.9)}), new, old, now=b.T0)
    d = novelty.decision(result)
    assert d.subjects == (new.id, old.id)
    assert novelty.verdict([d]) == "duplicate"


async def test_novelty_extension_is_novel(cassette: ClientFactory):
    new, old = (
        _claim("A says B at scale.", "https://arxiv.org/abs/n"),
        _claim("A says B.", "https://arxiv.org/abs/o"),
    )
    result = await novelty.judge(_jev(cassette, {"relation": (0.1, 0.8, 0.1)}), new, old, now=b.T0)
    assert novelty.verdict([novelty.decision(result)]) == "novel"


def test_novelty_verdict_edges():
    assert novelty.verdict([]) == "novel"  # no candidate pair: nothing to duplicate
    failure = JevFailure(
        function="novelty", subjects=(b.claim().id, b.claim().id), reason="timeout", detail=""
    )
    assert novelty.verdict([novelty.decision(failure)]) == "unjudged"


# --- source_support: string match first ---------------------------------------------------


async def test_source_support_string_match_skips_jev(cassette: ClientFactory):
    jev = _jev(cassette)
    result = await source_support.check(jev, b.claim(), b.source(), now=b.T0)
    assert (result.verdict, result.via, result.decision) == ("supports", "string_match", None)
    assert jev.questions_asked == 0


async def test_source_support_asks_jev_when_text_differs(cassette: ClientFactory):
    other = SourceItem.new(
        line=b.LINE_IRI,
        adapter="arxiv",
        url="https://arxiv.org/abs/x",
        title="t",
        text="Unrelated text.",
        fetched_at=b.T0,
    )
    answers = {"support": {"supports": 0.1, "contradicts": 0.7, "says_nothing": 0.2}}
    result = await source_support.check(_jev(cassette, answers), b.claim(), other, now=b.T0)
    assert (result.verdict, result.via) == ("contradicts", "jev")
    assert result.decision is not None and result.decision.outcome == "reject"


# --- source_trust / report_ordering -------------------------------------------------------


async def test_source_trust_levels(cassette: ClientFactory):
    low = await source_trust.judge(
        _jev(cassette, {"trust": (1.0, 0.0, 0.0, 0.0)}), b.source(), now=b.T0
    )
    assert source_trust.decision(low).outcome == "reject"


async def test_report_ordering_sorts_by_importance_unjudged_last(cassette: ClientFactory):
    a, c = (
        _claim("Minor thing.", "https://arxiv.org/abs/a"),
        _claim("Big shift.", "https://arxiv.org/abs/c"),
    )
    da = report_ordering.decision(
        await report_ordering.judge(
            _jev(cassette, {"importance": (0.0, 1.0, 0.0, 0.0)}), CTX, a, now=b.T0
        )
    )
    dc = report_ordering.decision(
        await report_ordering.judge(
            _jev(cassette, {"importance": (0.0, 0.0, 0.0, 1.0)}), CTX, c, now=b.T0
        )
    )
    lost = report_ordering.decision(
        JevFailure(
            function="report_ordering", subjects=(b.claim().id,), reason="timeout", detail=""
        )
    )
    assert report_ordering.order([da, lost, dc]) == [c.id, a.id, b.claim().id]


# --- rubrics -------------------------------------------------------------------------------


async def test_rubric_claim_passes_only_when_every_axis_clears(cassette: ClientFactory):
    st = rubric_claim.state(CTX, b.claim(), b.source(), "段落", ["stored"])
    ok = await rubric_claim.judge(_jev(cassette), b.report(), b.claim(), st, now=b.T0)
    assert rubric_claim.decision(ok).outcome == "accept"
    assert isinstance(ok, Judgment)
    assert rubric_claim.Answers.of(ok).grounded == 1.0


async def test_rubric_claim_one_low_axis_fails(cassette: ClientFactory):
    st = rubric_claim.state(CTX, b.claim(), b.source(), None, [])
    low = await rubric_claim.judge(
        _jev(cassette, {"grounded": (1.0, 0.0, 0.0)}), b.report(), b.claim(), st, now=b.T0
    )
    assert rubric_claim.decision(low).outcome == "reject"


async def test_rubric_report_unsupported_statement_fails(cassette: ClientFactory):
    st = rubric_report.state(CTX, "本文です。", [b.claim().text])
    result = await rubric_report.judge(
        _jev(cassette, {"unsupported_statement": 0.9}), b.report().id, st, now=b.T0
    )
    assert rubric_report.decision(result).outcome == "reject"
