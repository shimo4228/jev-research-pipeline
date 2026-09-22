"""Jev core: the output model is the questions, one request per ask, raw answers kept,
a failed request becomes "unjudged"."""

import json
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import UseEnumMemberDocstrings

from jev_research_pipeline.jev import (
    JEV_MODEL,
    Ask,
    JevClient,
    JevFailure,
    JevState,
    Judged,
    decide,
)
from jev_research_pipeline.jev.core import output_of
from jev_research_pipeline.model import ChoiceAnswer, NoulAnswer, ScoreAnswer, Threshold
from jev_research_pipeline.model.nodes import Probability

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev


class Depth(UseEnumMemberDocstrings, IntEnum):
    vague = 0
    """A slogan with no testable content."""
    specific = 1
    """Names a method and a measured effect."""


class Answers(BaseModel):
    """Judge one unit of text."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    checkable: Probability = Field(description="Does `unit.text` state a checkable claim?")
    depth: Depth = Field(description="How specific is the claim?")
    kind: Literal["empirical", "normative"] = Field(
        description="What kind of statement is it? `empirical` reports an observation or "
        "measurement; `normative` says what should be done."
    )


ASK = Ask(function="claim_detection", version="v1", output=Answers, instructions="Judge it.")
STATE: JevState = {"unit": {"text": "x"}}


def _reworded() -> Ask[Any]:
    class Other(BaseModel):
        """Judge one unit of text."""

        checkable: Probability = Field(description="Other wording?")
        depth: Depth = Field(description="How specific is the claim?")
        kind: Literal["empirical", "normative"] = Field(description="What kind?")

    return Ask(function="claim_detection", version="v1", output=Other, instructions="Judge it.")


def test_ask_hash_changes_with_wording():
    assert ASK.sha256 != _reworded().sha256
    assert ASK.sha256 == Ask(**{**vars(ASK)}).sha256


async def test_every_field_becomes_one_question_in_one_request(
    cassette: ClientFactory, cassette_path: Path
):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    # Read what went on the wire from the recording: under replay the fake never runs.
    recorded = json.loads(cassette_path.read_text(encoding="utf-8"))
    assert len(recorded) == 1
    questions = json.loads(next(iter(recorded.values()))["request_body"])["questions"]
    assert {name: q["type"] for name, q in questions.items()} == {
        "checkable": "noul",
        "depth": "score",
        "kind": "choice",
    }
    assert questions["depth"]["criteria"] == [
        "A slogan with no testable content.",
        "Names a method and a measured effect.",
    ]


async def test_judge_returns_the_output_and_the_raw_answers(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev({"checkable": 0.9, "depth": (0.25, 0.75)})), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, Judged)
    assert result.output.checkable == 0.9
    assert result.output.depth is Depth.specific
    j = result.judgment
    assert j.model == JEV_MODEL
    assert j.bundle_sha256 == ASK.sha256
    assert j.answer("checkable") == NoulAnswer(key="checkable", p_yes=0.9)
    assert j.answer("depth") == ScoreAnswer(
        key="depth", levels=("vague", "specific"), probabilities=(0.25, 0.75), score=0.75
    )
    kind = j.answer("kind")
    assert isinstance(kind, ChoiceAnswer)
    assert kind.argmax == "empirical"
    assert jev.questions_asked == 3


async def test_a_stored_judgment_replays_to_the_same_output(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev({"checkable": 0.9, "depth": (0.6, 0.4)})), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, Judged)
    assert output_of(Answers, result.judgment) == result.output


async def test_same_state_same_judgment_id(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    a = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    c = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(a, Judged) and isinstance(c, Judged)
    assert a.judgment.id == c.judgment.id


async def test_api_error_is_a_failure_not_an_exception(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev(status=400)), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "api_error"
    assert jev.questions_asked == 3


async def test_unpinned_model_in_response_is_a_failure(cassette: ClientFactory):
    # Aliases drift: an answer from any model other than the pinned one is not recorded.
    jev = JevClient(cassette(fake_jev(model="jev-1.14.0")), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "model_mismatch"


async def test_malformed_distribution_is_a_failure(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev({"depth": (0.5, 0.2)})), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "bad_answer"


def _failure(sha: str) -> JevFailure:
    return JevFailure(
        function="claim_detection",
        subjects=(b.unit().id,),
        bundle_sha256=sha,
        reason="timeout",
        detail="t",
    )


def test_decide_unjudged_on_failure():
    d = decide(_failure(ASK.sha256), ask=ASK, thresholds=(), rule=lambda j: (True, 1.0))
    assert d.outcome == "unjudged"
    assert d.judgments == ()
    assert d.score is None


async def test_decide_records_thresholds_and_score(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    result = await jev.judge(ASK, (b.unit().id,), STATE, now=b.T0)
    assert isinstance(result, Judged)
    t = (Threshold(name="checkable", value=0.5),)
    d = decide(result, ask=ASK, thresholds=t, rule=lambda j: (False, 0.2))
    assert (d.outcome, d.score, d.thresholds, d.judgments) == (
        "reject",
        0.2,
        t,
        (result.judgment.id,),
    )


def test_reworded_ask_yields_a_distinct_decision():
    # Same function, subjects and version, different wording → a different Decision @id,
    # so decisions made under old wording are never silently overwritten.
    reworded = _reworded()
    a = decide(_failure(ASK.sha256), ask=ASK, thresholds=(), rule=lambda j: (True, 1.0))
    c = decide(_failure(reworded.sha256), ask=reworded, thresholds=(), rule=lambda j: (True, 1.0))
    assert a.policy == c.policy
    assert a.id != c.id
    assert (a.bundle_sha256, c.bundle_sha256) == (ASK.sha256, reworded.sha256)


def test_decide_rejects_a_result_from_another_ask():
    with pytest.raises(ValueError, match="another ask"):
        decide(_failure("0" * 64), ask=ASK, thresholds=(), rule=lambda j: (True, 1.0))
