"""Jev core: question bundles, the pinned client, answer conversion, Decision building.

One Jev use = one Bundle of narrow questions over one state in one request (packet
"judgment map"). Code owns everything around it: building the state, the thresholds,
and the Decision. A failed request never raises into the pipeline — it becomes a
JevFailure, and decide() turns that into a Decision with outcome "unjudged".
"""

from collections.abc import Callable
from typing import Annotated, Final, Literal, Self

import httpx2
from pydantic import AwareDatetime, Field, ValidationError, model_validator
from typesafe_sdk import (
    Choice,
    Noul,
    NoulCriteria,
    RetryPolicy,
    Score,
    TypeSafeAPIConnectionError,
    TypeSafeAPITimeoutError,
    TypeSafeError,
)
from typesafe_sdk import (
    ChoiceAnswer as SdkChoice,
)
from typesafe_sdk import (
    NoulAnswer as SdkNoul,
)
from typesafe_sdk import (
    ScoreAnswer as SdkScore,
)

from jev_research_pipeline.model import (
    SUBJECT_KINDS,
    Answer,
    ChoiceAnswer,
    Decision,
    JevFunction,
    Judgment,
    NoulAnswer,
    ScoreAnswer,
    Threshold,
)
from jev_research_pipeline.model.jsonld import Value, kind_of
from jev_research_pipeline.model.nodes import Key, NonEmptyText
from jev_research_pipeline.store import input_sha256

from ._sdk import JevState, SystemOne

JEV_MODEL: Final = "jev-1.13.0"
"""Pinned (decision 9): aliases like jev-latest drift with no published deprecation policy."""
JEV_TIMEOUT_S: Final = 10.0
"""Per HTTP operation; the SDK default, stated explicitly."""
JEV_RETRY: Final = RetryPolicy(max_retries=2, backoff_initial=0.5, backoff_max=5.0)
"""Retries 408/429/5xx and connection errors (SDK defaults, stated explicitly)."""


class Level(Value):
    """One Score level / Choice option. `description` is what Jev sees; for Score levels
    it must describe a concrete situation that stands on its own (vendor guidance)."""

    key: Key
    description: NonEmptyText


class NoulQ(Value):
    kind: Literal["noul"] = "noul"
    key: Key
    instructions: NonEmptyText
    if_true: str | None = None
    if_false: str | None = None


class ScoreQ(Value):
    kind: Literal["score"] = "score"
    key: Key
    instructions: NonEmptyText
    levels: tuple[Level, ...] = Field(min_length=2)
    """Ordered low → high; the answer's probabilities follow this order."""


class ChoiceQ(Value):
    kind: Literal["choice"] = "choice"
    key: Key
    instructions: NonEmptyText
    options: tuple[Level, ...] = Field(min_length=2)


QuestionSpec = Annotated[NoulQ | ScoreQ | ChoiceQ, Field(discriminator="kind")]


class Bundle(Value):
    """The questions one Jev function asks in one request. `sha256` (over the full wording)
    is Judgment.bundle_sha256: rewording a question yields new judgments, never a silent
    mix of old and new meanings under one id."""

    function: JevFunction
    version: Key
    questions: tuple[QuestionSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys_unique(self) -> Self:
        keys = [q.key for q in self.questions]
        if len(set(keys)) != len(keys):
            raise ValueError("question keys must be unique")
        for q in self.questions:
            levels = (
                q.levels if isinstance(q, ScoreQ) else q.options if isinstance(q, ChoiceQ) else ()
            )
            if len({lv.key for lv in levels}) != len(levels):
                raise ValueError(f"level/option keys of {q.key} must be unique")
        return self

    @property
    def sha256(self) -> str:
        return input_sha256(self.model_dump(mode="json"))

    @property
    def policy(self) -> str:
        return f"{self.function}@{self.version}"

    def to_sdk(self) -> dict[str, Noul | Score | Choice]:
        out: dict[str, Noul | Score | Choice] = {}
        for q in self.questions:
            match q:
                case NoulQ():
                    criteria = (
                        NoulCriteria(true=q.if_true, false=q.if_false)
                        if q.if_true is not None or q.if_false is not None
                        else None
                    )
                    out[q.key] = Noul(instructions=q.instructions, criteria=criteria)
                case ScoreQ():
                    out[q.key] = Score(
                        instructions=q.instructions, criteria=[lv.description for lv in q.levels]
                    )
                case ChoiceQ():
                    out[q.key] = Choice(
                        instructions=q.instructions,
                        criteria={o.key: o.description for o in q.options},
                    )
        return out


type FailureReason = Literal["timeout", "connection", "api_error", "model_mismatch", "bad_answer"]


class JevFailure(Value):
    """A Jev request that produced no usable Judgment. Becomes an "unjudged" Decision."""

    function: JevFunction
    subjects: tuple[str, ...]
    bundle_sha256: str
    reason: FailureReason
    detail: str


class _BadAnswer(ValueError):
    pass


def _convert(q: QuestionSpec, raw: object) -> Answer:
    match q:
        case NoulQ() if isinstance(raw, SdkNoul):
            return NoulAnswer(key=q.key, p_yes=raw.noul)
        case ScoreQ() if isinstance(raw, SdkScore):
            if set(raw.probabilities) != set(range(len(q.levels))):
                raise _BadAnswer(
                    f"{q.key}: score levels {sorted(raw.probabilities)} != asked {len(q.levels)}"
                )
            probs = tuple(raw.probabilities[i] for i in range(len(q.levels)))
            return ScoreAnswer(
                key=q.key, levels=tuple(lv.key for lv in q.levels), probabilities=probs
            )
        case ChoiceQ() if isinstance(raw, SdkChoice):
            if set(raw.probabilities) != {o.key for o in q.options}:
                raise _BadAnswer(f"{q.key}: choice labels {sorted(raw.probabilities)} != asked")
            probs = tuple(raw.probabilities[o.key] for o in q.options)
            return ChoiceAnswer(
                key=q.key, options=tuple(o.key for o in q.options), probabilities=probs
            )
        case _:
            raise _BadAnswer(f"{q.key}: missing or wrong-typed answer")


class JevClient:
    """The only door to Jev. `questions_asked` meters every question sent (operations
    section: Jev question count), including those whose request failed."""

    def __init__(self, http_client: httpx2.AsyncClient, *, api_key: str) -> None:
        self._jev = SystemOne(
            http_client, api_key=api_key, model=JEV_MODEL, retry=JEV_RETRY, timeout_s=JEV_TIMEOUT_S
        )
        self.questions_asked = 0

    async def aclose(self) -> None:
        await self._jev.aclose()

    async def judge(
        self, bundle: Bundle, subjects: tuple[str, ...], state: JevState, *, now: AwareDatetime
    ) -> Judgment | JevFailure:
        def fail(reason: FailureReason, detail: object) -> JevFailure:
            return JevFailure(
                function=bundle.function,
                subjects=subjects,
                bundle_sha256=bundle.sha256,
                reason=reason,
                detail=str(detail),
            )

        # Wiring errors are programming errors: raise before any request, never "unjudged".
        want = SUBJECT_KINDS[bundle.function]
        got = tuple(kind_of(s) for s in subjects)
        if got != want:
            raise ValueError(f"subjects for {bundle.function} must be kinds {want}, got {got}")
        self.questions_asked += len(bundle.questions)
        try:
            response = await self._jev.ask(state, bundle.to_sdk())
        except TypeSafeAPITimeoutError as e:
            return fail("timeout", e)
        except TypeSafeAPIConnectionError as e:
            return fail("connection", e)
        except TypeSafeError as e:
            return fail("api_error", e)
        if response.model != JEV_MODEL:
            return fail("model_mismatch", f"asked {JEV_MODEL}, answered by {response.model}")
        try:
            answers = tuple(_convert(q, response.answers.get(q.key)) for q in bundle.questions)
        except (_BadAnswer, ValidationError) as e:
            return fail("bad_answer", e)
        return Judgment.new(
            function=bundle.function,
            subjects=subjects,
            model=response.model,
            state_sha256=input_sha256(state),
            bundle_sha256=bundle.sha256,
            answers=answers,
            judged_at=now,
        )


type Rule = Callable[[Judgment], tuple[bool, float]]
"""Code policy over one Judgment: (accept?, the combined score compared to thresholds)."""


def decide(
    result: Judgment | JevFailure,
    *,
    bundle: Bundle,
    thresholds: tuple[Threshold, ...],
    rule: Rule,
) -> Decision:
    """Policy = bundle.policy, identity includes bundle.sha256. The result must come from
    this bundle's wording (a mismatch is a wiring error and raises)."""
    if result.bundle_sha256 != bundle.sha256:
        raise ValueError(f"result was produced by another bundle than {bundle.policy}")
    if isinstance(result, JevFailure):
        judgments: tuple[str, ...] = ()
        outcome: Literal["accept", "reject", "unjudged"] = "unjudged"
        value: float | None = None
    else:
        accept, value = rule(result)
        judgments = (result.id,)
        outcome = "accept" if accept else "reject"
    return Decision.new(
        function=result.function,
        subjects=result.subjects,
        policy=bundle.policy,
        bundle_sha256=bundle.sha256,
        judgments=judgments,
        thresholds=thresholds,
        outcome=outcome,
        score=value,
    )


def threshold(thresholds: tuple[Threshold, ...], name: str) -> float:
    for t in thresholds:
        if t.name == name:
            return t.value
    raise KeyError(name)


def noul(j: Judgment, key: str) -> float:
    a = j.answer(key)
    if not isinstance(a, NoulAnswer):
        raise TypeError(f"{key} is not a Noul answer")
    return a.p_yes


def score(j: Judgment, key: str) -> ScoreAnswer:
    a = j.answer(key)
    if not isinstance(a, ScoreAnswer):
        raise TypeError(f"{key} is not a Score answer")
    return a


def choice(j: Judgment, key: str) -> ChoiceAnswer:
    a = j.answer(key)
    if not isinstance(a, ChoiceAnswer):
        raise TypeError(f"{key} is not a Choice answer")
    return a
