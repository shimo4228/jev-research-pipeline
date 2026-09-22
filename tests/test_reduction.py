"""Step 9: reduction ① threshold fit, ② label → pydantic-evals Case, ③ rule candidates."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic_evals import Dataset

from jev_research_pipeline.jev import claim_detection, relevance_triage
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import (
    Claim,
    Decision,
    GraphNodeType,
    Judgment,
    Label,
    NoulAnswer,
    SourceItem,
    Unit,
)
from jev_research_pipeline.reduction import (
    DecisionLog,
    RuleConfig,
    export_cases,
    fit_thresholds,
    rule_candidates,
    write_proposal,
)
from jev_research_pipeline.store import GraphStore

from . import builders as b

CTX = LineContext(line=b.line(), vocabulary=("agent memory",))


def _world(n: int, *, correct_if: str = "high") -> list[GraphNodeType]:
    """n sources → units → claims, each with a claim_detection judgment whose
    checkable_claim p_yes = i/n, and a Label: correct iff p ≥ 0.7 (so the fitted threshold
    for checkable_claim should move up from 0.5 toward 0.7)."""
    nodes: list[GraphNodeType] = []
    for i in range(n):
        p = i / n
        text = f"Claim {i} about agent memory."
        adapter = "github" if i % 2 else "arxiv"
        src = SourceItem.new(
            line=b.LINE_IRI,
            adapter=adapter,
            url=f"https://example.org/{i}",
            title="t",
            text=text,
            fetched_at=b.T0,
            published_at=b.T0.date() - timedelta(days=400 if adapter == "github" else 3),
        )
        unit = Unit.cut(src, start=0, end=len(text), granularity="sentence")
        claim = Claim.from_unit(unit, line=b.LINE_IRI)
        j = Judgment.new(
            function="claim_detection",
            subjects=(unit.id,),
            model="jev-1.13.0",
            state_sha256=claim_detection_state_sha(unit, src),
            bundle_sha256=claim_detection.ASK.sha256,
            answers=(
                NoulAnswer(key="checkable_claim", p_yes=p),
                NoulAnswer(key="relevant", p_yes=0.9),
            ),
            judged_at=b.T0,
        )
        verdict = "correct" if (p >= 0.7) == (correct_if == "high") else "incorrect"
        label = Label.new(claim=claim.id, report=b.report().id, verdict=verdict, harvested_at=b.T0)
        # relevance_triage decision: rejected exactly for github sources (a code feature).
        tri = Decision.new(
            function="relevance_triage",
            subjects=(src.id,),
            policy=relevance_triage.ASK.policy,
            bundle_sha256=relevance_triage.ASK.sha256,
            judgments=(b.judgment().id,),
            thresholds=relevance_triage.THRESHOLDS,
            outcome="reject" if adapter == "github" else "accept",
            score=0.2 if adapter == "github" else 0.8,
        )
        nodes += [src, unit, claim, j, label, tri]
    return nodes


def claim_detection_state_sha(unit: Unit, src: SourceItem) -> str:
    from jev_research_pipeline.store import input_sha256

    return input_sha256(claim_detection.state(CTX, unit, src))


# --- decision log --------------------------------------------------------------------------


def test_log_links_judgments_to_labeled_claims():
    log = DecisionLog.from_nodes(_world(10))
    pairs = log.labeled_pairs("claim_detection")
    assert len(pairs) == 10
    assert all(isinstance(j, Judgment) and v in ("correct", "incorrect") for j, v in pairs)


# --- ① fit ---------------------------------------------------------------------------------


def test_fit_moves_threshold_toward_the_gold_boundary():
    proposals = fit_thresholds(DecisionLog.from_nodes(_world(40)), min_gold=10)
    p = next(
        p for p in proposals if (p.function, p.threshold) == ("claim_detection", "checkable_claim")
    )
    assert p.current == 0.5
    assert p.proposed == pytest.approx(0.7)
    assert p.accuracy_proposed > p.accuracy_current
    assert p.n_gold == 40


def test_fit_needs_enough_gold():
    assert fit_thresholds(DecisionLog.from_nodes(_world(5)), min_gold=10) == []


def test_proposal_file_is_written_not_applied(tmp_path: Path):
    proposals = fit_thresholds(DecisionLog.from_nodes(_world(40)), min_gold=10)
    path = write_proposal(tmp_path, proposals, day=date(2026, 9, 22))
    assert path.name == "thresholds-2026-09-22.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["applied"] is False
    assert {"function", "threshold", "current", "proposed"} <= set(data["proposals"][0])
    assert claim_detection.THRESHOLDS[0].value == 0.5  # code config untouched


# --- ② Cases ---------------------------------------------------------------------------------


async def test_export_cases_roundtrip_and_run(tmp_path: Path):
    nodes = _world(6)
    path = export_cases(DecisionLog.from_nodes(nodes), CTX, tmp_path / "cases.yaml")
    dataset = Dataset[dict[str, object], str, dict[str, object]].from_file(path)
    assert len(dataset.cases) == 6
    case = dataset.cases[0]
    assert case.expected_output in ("correct", "incorrect")
    assert case.metadata is not None and case.metadata["state_matches_judgment"] is True

    # The exported cases run under pydantic-evals: replay the recorded decision as the task.
    recorded = {c.name: c.expected_output for c in dataset.cases}
    report = await dataset.evaluate(
        lambda inputs: recorded[str(inputs["claim_id"])] or "", progress=False
    )
    assert len(report.cases) == 6
    assert all(all(a.value is True for a in c.assertions.values()) for c in report.cases)


def test_exported_case_inputs_are_the_judgment_state(tmp_path: Path):
    path = export_cases(DecisionLog.from_nodes(_world(2)), CTX, tmp_path / "cases.yaml")
    dataset = Dataset[dict[str, object], str, dict[str, object]].from_file(path)
    inputs = dataset.cases[0].inputs
    assert set(inputs) == {"claim_id", "function", "state"}
    assert inputs["function"] == "claim_detection"


# --- ③ rule candidates ------------------------------------------------------------------------


def test_rule_candidate_found_for_a_code_feature():
    lines = rule_candidates(
        DecisionLog.from_nodes(_world(80)),
        RuleConfig(min_n=30, min_agreement=0.95),
        today=b.T0.date(),
    )
    assert any(
        "relevance_triage" in ln and "adapter=github" in ln and "reject" in ln for ln in lines
    )


def test_rule_candidates_respect_min_n():
    lines = rule_candidates(
        DecisionLog.from_nodes(_world(20)),
        RuleConfig(min_n=30, min_agreement=0.95),
        today=b.T0.date(),
    )
    assert lines == []


def test_rule_config_defaults():
    assert (RuleConfig().min_n, RuleConfig().min_agreement) == (30, 0.95)


def test_log_from_store_partition(tmp_path: Path):
    part = GraphStore(tmp_path).line("akc")
    part.put(_world(4))
    log = DecisionLog.from_partition(part)
    assert len(log.labels) == 4


# --- review fixes (dad3066) ------------------------------------------------------------------


def _rejudged(nodes: list[GraphNodeType]) -> list[GraphNodeType]:
    """Add a stale-bundle duplicate of every claim_detection judgment (a reworded re-run)."""
    extra: list[GraphNodeType] = []
    for n in nodes:
        if isinstance(n, Judgment) and n.function == "claim_detection":
            extra.append(
                Judgment.new(
                    function=n.function,
                    subjects=n.subjects,
                    model=n.model,
                    state_sha256=n.state_sha256,
                    bundle_sha256="d" * 64,
                    answers=n.answers,
                    judged_at=b.T0.replace(hour=1),
                )
            )
    return nodes + extra


def test_min_gold_counts_distinct_labeled_claims():
    # 6 labeled claims judged twice must not pass a gate of 10.
    assert fit_thresholds(DecisionLog.from_nodes(_rejudged(_world(6))), min_gold=10) == []


def test_fit_uses_only_current_bundle_judgments():
    proposals = fit_thresholds(DecisionLog.from_nodes(_rejudged(_world(40))), min_gold=10)
    p = next(
        p for p in proposals if (p.function, p.threshold) == ("claim_detection", "checkable_claim")
    )
    assert p.n_gold == 40


def test_novelty_is_not_fitted_against_correctness():
    from jev_research_pipeline.reduction.fit import SPECS

    assert all(spec.function != "novelty" for spec, _, _, _ in SPECS)


def test_rule_needs_to_beat_the_complement():
    # Every triage decision accepted: no split carries information, so no candidate.
    nodes = [
        n.model_copy(update={"outcome": "accept"}) if isinstance(n, Decision) else n
        for n in _world(80)
    ]
    assert rule_candidates(DecisionLog.from_nodes(nodes), RuleConfig(), today=b.T0.date()) == []


def test_case_prefers_the_judgment_matching_the_rebuilt_state(tmp_path: Path):
    path = export_cases(DecisionLog.from_nodes(_rejudged(_world(2))), CTX, tmp_path / "c.yaml")
    dataset = Dataset[dict[str, object], str, dict[str, object]].from_file(path)
    assert all(
        c.metadata is not None and c.metadata["state_matches_judgment"] is True
        for c in dataset.cases
    )
