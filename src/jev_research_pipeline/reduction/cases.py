"""Reduction ②: each labeled claim becomes a pydantic-evals Case (decision 6).

Case inputs = the claim_detection state of the claim's unit *for the question it was
judged against* (the state that Judgment was asked on — rebuilt from the store, since
Judgments keep only its sha256; the metadata records whether the rebuilt state still
hashes to the stored one) + the function name + the claim @id. Expected output = the
author's verdict. The YAML file is a regression
suite: any future judging path must reproduce the author's verdicts on it.
"""

from pathlib import Path

from pydantic import JsonValue
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import EqualsExpected

from jev_research_pipeline.jev import claim_detection
from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.store import input_sha256

from .log import DecisionLog

type Inputs = dict[str, JsonValue]
type Meta = dict[str, JsonValue]


def export_cases(log: DecisionLog, ctx: LineContext, path: Path) -> Path:
    cases: list[Case[Inputs, str, Meta]] = []
    for claim_id, verdict in sorted(log.gold().items()):
        claim = log.claims.get(claim_id)
        unit = log.units.get(claim.unit) if claim else None
        source = log.sources.get(unit.source) if unit else None
        if claim is None or unit is None or source is None:
            continue
        candidates = [
            j
            for j in log.judgments
            if j.function == "claim_detection" and j.subjects[:1] == (unit.id,)
        ]
        # Prefer the judgment asked on exactly this state; else the latest one.
        recorded = max(candidates, key=lambda j: (j.judged_at, j.id), default=None)
        question = log.questions.get(recorded.subjects[1]) if recorded else None
        if question is None:
            continue  # no question to anchor the case on: it would not be replayable
        state = claim_detection.state(question, unit, source)
        rebuilt = input_sha256(state)
        cases.append(
            Case(
                name=claim_id,
                inputs={
                    "claim_id": claim_id,
                    "function": "claim_detection",
                    "question": question.id,
                    "state": state,
                },
                expected_output=verdict,
                metadata={
                    "state_matches_judgment": recorded is not None
                    and recorded.state_sha256 == rebuilt,
                    "judgment": recorded.id if recorded else None,
                },
            )
        )
    dataset = Dataset[Inputs, str, Meta](
        name=f"jrp-labels-{ctx.line.slug}", cases=cases, evaluators=[EqualsExpected()]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_file(path, schema_path=None)
    return path
