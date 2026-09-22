"""Jev core: question bundles, one request per bundle, raw answers, unjudged on failure."""

import pytest
from pydantic import ValidationError

from jev_research_pipeline.jev import (
    JEV_MODEL,
    Bundle,
    ChoiceQ,
    JevClient,
    JevFailure,
    Level,
    NoulQ,
    ScoreQ,
    decide,
)
from jev_research_pipeline.model import ChoiceAnswer, Judgment, NoulAnswer, ScoreAnswer, Threshold

from . import builders as b
from .conftest import ClientFactory
from .fakes import fake_jev

BUNDLE = Bundle(
    function="claim_detection",
    version="v1",
    questions=(
        NoulQ(key="checkable", instructions="Does `unit.text` state a checkable claim?"),
        ScoreQ(
            key="depth",
            instructions="How specific is the claim?",
            levels=(
                Level(key="vague", description="A slogan with no testable content."),
                Level(key="specific", description="Names a method and a measured effect."),
            ),
        ),
        ChoiceQ(
            key="kind",
            instructions="What kind of statement is it?",
            options=(
                Level(key="empirical", description="Reports an observation or measurement."),
                Level(key="normative", description="Says what should be done."),
            ),
        ),
    ),
)


def test_bundle_keys_unique():
    with pytest.raises(ValidationError, match="unique"):
        Bundle(
            function="claim_detection",
            version="v1",
            questions=(NoulQ(key="a", instructions="x"), NoulQ(key="a", instructions="y")),
        )


def test_bundle_hash_changes_with_wording():
    reworded = BUNDLE.model_copy(
        update={
            "questions": (
                NoulQ(key="checkable", instructions="Other wording?"),
                *BUNDLE.questions[1:],
            )
        }
    )
    assert BUNDLE.sha256 != reworded.sha256
    assert BUNDLE.sha256 == Bundle.model_validate(BUNDLE.model_dump()).sha256


def test_bundle_to_sdk_keeps_level_order():
    sdk = BUNDLE.to_sdk()
    assert list(sdk) == ["checkable", "depth", "kind"]
    depth = sdk["depth"].model_dump()
    assert depth["criteria"] == [
        "A slogan with no testable content.",
        "Names a method and a measured effect.",
    ]


async def test_judge_returns_raw_answers(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev({"checkable": 0.9, "depth": (0.25, 0.75)})), api_key="replay")
    result = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": b.unit().text}}, now=b.T0)
    assert isinstance(result, Judgment)
    assert result.model == JEV_MODEL
    assert result.bundle_sha256 == BUNDLE.sha256
    assert result.answer("checkable") == NoulAnswer(key="checkable", p_yes=0.9)
    assert result.answer("depth") == ScoreAnswer(
        key="depth", levels=("vague", "specific"), probabilities=(0.25, 0.75)
    )
    kind = result.answer("kind")
    assert isinstance(kind, ChoiceAnswer)
    assert kind.argmax == "empirical"
    assert jev.questions_asked == 3


async def test_same_state_same_judgment_id(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev()), api_key="replay")
    a = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": "x"}}, now=b.T0)
    c = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": "x"}}, now=b.T0)
    assert isinstance(a, Judgment) and isinstance(c, Judgment)
    assert a.id == c.id


async def test_api_error_is_a_failure_not_an_exception(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev(status=400)), api_key="replay")
    result = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": "x"}}, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "api_error"
    assert jev.questions_asked == 3


async def test_unpinned_model_in_response_is_a_failure(cassette: ClientFactory):
    # Aliases drift: an answer from any model other than the pinned one is not recorded.
    jev = JevClient(cassette(fake_jev(model="jev-1.14.0")), api_key="replay")
    result = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": "x"}}, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "model_mismatch"


async def test_malformed_distribution_is_a_failure(cassette: ClientFactory):
    jev = JevClient(cassette(fake_jev({"depth": (0.5, 0.2)})), api_key="replay")
    result = await jev.judge(BUNDLE, (b.unit().id,), {"unit": {"text": "x"}}, now=b.T0)
    assert isinstance(result, JevFailure)
    assert result.reason == "bad_answer"


def test_decide_unjudged_on_failure():
    failure = JevFailure(
        function="claim_detection",
        subjects=(b.unit().id,),
        bundle_sha256=BUNDLE.sha256,
        reason="timeout",
        detail="t",
    )
    d = decide(failure, bundle=BUNDLE, thresholds=(), rule=lambda j: (True, 1.0))
    assert d.outcome == "unjudged"
    assert d.judgments == ()
    assert d.score is None


def test_decide_records_thresholds_and_score():
    t = (Threshold(name="checkable", value=0.5),)
    judged = b.judgment().model_copy(update={"bundle_sha256": BUNDLE.sha256})
    d = decide(judged, bundle=BUNDLE, thresholds=t, rule=lambda j: (False, 0.2))
    assert (d.outcome, d.score, d.thresholds, d.judgments) == ("reject", 0.2, t, (judged.id,))


def test_reworded_bundle_yields_a_distinct_decision():
    # Same function, subjects and version, different wording → a different Decision @id,
    # so decisions made under old wording are never silently overwritten.
    reworded = BUNDLE.model_copy(
        update={
            "questions": (
                NoulQ(key="checkable", instructions="Other wording?"),
                *BUNDLE.questions[1:],
            )
        }
    )
    failure = JevFailure(
        function="claim_detection",
        subjects=(b.unit().id,),
        bundle_sha256=BUNDLE.sha256,
        reason="timeout",
        detail="",
    )
    other = failure.model_copy(update={"bundle_sha256": reworded.sha256})
    a = decide(failure, bundle=BUNDLE, thresholds=(), rule=lambda j: (True, 1.0))
    c = decide(other, bundle=reworded, thresholds=(), rule=lambda j: (True, 1.0))
    assert a.policy == c.policy
    assert a.id != c.id
    assert (a.bundle_sha256, c.bundle_sha256) == (BUNDLE.sha256, reworded.sha256)


def test_decide_rejects_a_result_from_another_bundle():
    with pytest.raises(ValueError, match="bundle"):
        decide(b.judgment(), bundle=BUNDLE, thresholds=(), rule=lambda j: (True, 1.0))
