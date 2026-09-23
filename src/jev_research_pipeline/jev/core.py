"""Jev core: one Pydantic output model per function, called through pydantic-ai's typesafe model.

Migrated 2026-09-23 from a hand-rolled bundle layer: the same abstraction now drives both
models the pipeline uses, and the questions live on the types instead of in a parallel
structure that had to be converted.

One Jev use = one output model over one state in one request. A field is one question —
`float` bounded 0..1 is a Noul and comes back as the raw probability, a `Literal` is a
Choice, an `IntEnum` with a docstring per member is a Score. Code owns everything around
it: the state, the thresholds and the Decision. A failed request never raises into the
pipeline — it becomes a JevFailure, and decide() turns that into an "unjudged" Decision.

Trade-off of the migration: a Noul's true/false criteria collapse into one field
description, so both sides of the condition have to be written into the question itself.
"""

import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated, Any, Final, Literal, TypeAliasType, cast, get_args, get_origin

import httpx2
from pydantic import AwareDatetime, BaseModel, JsonValue, ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.typesafe import TypeSafeModel, TypeSafeModelSettings
from pydantic_ai.providers.typesafe import TypeSafeProvider
from pydantic_ai.tools import GenerateToolJsonSchema

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
from jev_research_pipeline.model.nodes import Key
from jev_research_pipeline.store import input_sha256
from jev_research_pipeline.telemetry import span

JEV_MODEL: Final = "jev-1.13.0"
"""Pinned (decision 9): aliases like jev-latest drift with no published deprecation policy."""
JEV_TIMEOUT_S: Final = 10.0
"""Per request. Retries stay at the SDK default (2, 0.5s → 5s, on 408/429/5xx)."""

type JevState = dict[str, JsonValue]
"""Named JSON fields (vendor guidance: prefer named fields when state has several parts)."""


@dataclass(frozen=True)
class Ask[OutputT: BaseModel]:
    """One Jev function: the output model whose fields are its questions, plus the
    instructions that go along with every one of them.

    `sha256` covers everything that decides what a stored answer means: the function, the
    version, the instructions, and the schema pydantic-ai *sends* (plain
    model_json_schema() drops the member docstrings that become a Score's levels), plus
    each Score's level names, which the schema renders as bare consts although
    ScoreAnswer.levels stores them and the accessors look them up by name. Rewording or
    renaming therefore yields new judgments, never a silent mix of old and new meanings
    under one id, and never a cached answer whose levels no longer match the code.
    """

    function: JevFunction
    version: Key
    output: type[OutputT]
    instructions: str

    @property
    def sha256(self) -> str:
        schema = cast(
            JsonValue, self.output.model_json_schema(schema_generator=GenerateToolJsonSchema)
        )
        levels: JsonValue = {
            name: list(score_levels(field.annotation))
            for name, field in self.output.model_fields.items()
            if isinstance(field.annotation, type) and issubclass(field.annotation, IntEnum)
        }
        return input_sha256(
            {
                "function": self.function,
                "version": self.version,
                "instructions": self.instructions,
                "schema": schema,
                "levels": levels,
            }
        )

    @property
    def policy(self) -> str:
        return f"{self.function}@{self.version}"


@dataclass(frozen=True)
class Judged[OutputT: BaseModel]:
    """A successful Jev request: the filled output model, and the Judgment that stores the
    raw distributions behind it."""

    output: OutputT
    judgment: Judgment

    @property
    def bundle_sha256(self) -> str:
        return self.judgment.bundle_sha256

    @property
    def function(self) -> JevFunction:
        return self.judgment.function

    @property
    def subjects(self) -> tuple[str, ...]:
        return self.judgment.subjects


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


def score_levels(enum: type[IntEnum]) -> tuple[str, ...]:
    """Member names low → high. The values must be 0..n-1: that is what a Jev rubric is."""
    members = sorted(enum, key=lambda m: m.value)
    if [m.value for m in members] != list(range(len(members))):
        raise TypeError(f"{enum.__name__} levels must be 0..{len(members) - 1}")
    return tuple(m.name for m in members)


def _resolved(annotation: object) -> object:
    """`Probability` and friends are PEP 695 aliases over Annotated; the question type is
    what they unwrap to."""
    while True:
        if isinstance(annotation, TypeAliasType):
            annotation = cast(object, annotation.__value__)
        elif get_origin(annotation) is Annotated:
            annotation = cast(object, get_args(annotation)[0])
        else:
            return annotation


def _choice_options(annotation: object) -> tuple[str, ...] | None:
    if get_origin(annotation) is Literal:
        return tuple(str(a) for a in get_args(annotation))
    return None


def _distribution(details: dict[str, Any], name: str) -> dict[str, float]:
    probabilities = cast(dict[str, dict[str, float]], details.get("probabilities", {}))
    if name not in probabilities:
        raise _BadAnswer(f"{name}: no distribution in provider_details")
    return probabilities[name]


def _answer(name: str, raw_annotation: object, value: object, details: dict[str, Any]) -> Answer:
    """One stored Answer per output field, distributions kept exactly as Jev sent them."""
    annotation = _resolved(raw_annotation)
    if annotation is float:
        if not isinstance(value, float):
            raise _BadAnswer(f"{name}: expected a probability, got {value!r}")
        return NoulAnswer(key=name, p_yes=value)
    if isinstance(annotation, type) and issubclass(annotation, IntEnum):
        levels = score_levels(annotation)
        dist = _distribution(details, name)
        if set(dist) != {str(i) for i in range(len(levels))}:
            raise _BadAnswer(f"{name}: score levels {sorted(dist)} != asked {len(levels)}")
        scores = cast(dict[str, float], details.get("scores", {}))
        return ScoreAnswer(
            key=name,
            levels=levels,
            probabilities=tuple(dist[str(i)] for i in range(len(levels))),
            score=scores.get(name),
        )
    if (options := _choice_options(cast(object, annotation))) is not None:
        dist = _distribution(details, name)
        if set(dist) != set(options):
            raise _BadAnswer(f"{name}: choice labels {sorted(dist)} != asked")
        return ChoiceAnswer(
            key=name, options=options, probabilities=tuple(dist[o] for o in options)
        )
    raise TypeError(f"{name}: {annotation!r} is not a Jev question type")


def answers_of(output: BaseModel, details: dict[str, Any]) -> tuple[Answer, ...]:
    return tuple(
        _answer(name, field.annotation, getattr(output, name), details)
        for name, field in type(output).model_fields.items()
    )


def _field_value(raw_annotation: object, answer: Answer) -> object:
    """The value pydantic-ai filled the field with, rebuilt from a stored answer."""
    annotation = _resolved(raw_annotation)
    if isinstance(answer, NoulAnswer):
        return answer.p_yes
    if isinstance(answer, ScoreAnswer):
        # The same rounding pydantic-ai applies to a live answer (half goes up).
        raw = (
            answer.score
            if answer.score is not None
            else answer.expected_position * (len(answer.levels) - 1)
        )
        level = min(int(raw + 0.5), len(answer.levels) - 1)
        assert isinstance(annotation, type)
        return annotation(level)
    return answer.argmax


def output_of[OutputT: BaseModel](output: type[OutputT], judgment: Judgment) -> OutputT:
    """Rebuild a filled output model from a stored Judgment (the stage cache replays
    judgments; the answers are what was stored, so nothing is asked twice)."""
    fields = output.model_fields
    return output.model_validate(
        {
            name: _field_value(field.annotation, judgment.answer(name))
            for name, field in fields.items()
        }
    )


class JevClient:
    """The only door to Jev. `questions_asked` meters every question sent (operations
    section: Jev question count), including those whose request failed."""

    def __init__(self, http_client: httpx2.AsyncClient, *, api_key: str) -> None:
        self._model = TypeSafeModel(
            JEV_MODEL, provider=TypeSafeProvider(api_key=api_key, http_client=http_client)
        )
        self._settings = TypeSafeModelSettings(timeout=JEV_TIMEOUT_S)
        self.questions_asked = 0

    async def aclose(self) -> None:
        """The HTTP client is owned by the caller; nothing of ours outlives a run."""

    async def judge[OutputT: BaseModel](
        self,
        ask: Ask[OutputT],
        subjects: tuple[str, ...],
        state: JevState,
        *,
        now: AwareDatetime,
    ) -> Judged[OutputT] | JevFailure:
        def fail(reason: FailureReason, detail: object) -> JevFailure:
            return JevFailure(
                function=ask.function,
                subjects=subjects,
                bundle_sha256=ask.sha256,
                reason=reason,
                detail=str(detail),
            )

        # Wiring errors are programming errors: raise before any request, never "unjudged".
        want = SUBJECT_KINDS[ask.function]
        got = tuple(kind_of(s) for s in subjects)
        if got != want:
            raise ValueError(f"subjects for {ask.function} must be kinds {want}, got {got}")
        questions = len(ask.output.model_fields)
        self.questions_asked += questions
        with span(
            f"jev.{ask.function}",
            function=ask.function,
            questions=questions,
            subjects=len(subjects),
            model=JEV_MODEL,
        ) as current:
            result = await self._ask(ask, subjects, state, fail=fail, now=now)
            current.set_attribute(
                "jrp.outcome", "judged" if isinstance(result, Judged) else result.reason
            )
            return result

    async def _ask[OutputT: BaseModel](
        self,
        ask: Ask[OutputT],
        subjects: tuple[str, ...],
        state: JevState,
        *,
        fail: Callable[[FailureReason, object], JevFailure],
        now: AwareDatetime,
    ) -> Judged[OutputT] | JevFailure:
        agent = Agent(
            self._model,
            output_type=ask.output,
            instructions=ask.instructions,
            model_settings=self._settings,
        )
        try:
            run = await agent.run(json.dumps(state, ensure_ascii=False, sort_keys=True))
        except ModelHTTPError as e:
            return fail("api_error", e)
        except UnexpectedModelBehavior as e:
            return fail("bad_answer", e)
        except ModelAPIError as e:
            # The SDK's timeout is a connection error; only the cause tells them apart.
            return fail("timeout" if isinstance(e.__cause__, TimeoutError) else "connection", e)
        response: ModelResponse = run.response
        if response.model_name != JEV_MODEL:
            return fail("model_mismatch", f"asked {JEV_MODEL}, answered by {response.model_name}")
        try:
            # TypeError is not caught: an output field Jev cannot be asked about is a
            # wiring error, and swallowing it would make every subject pay for a request
            # whose Decision is "unjudged" forever.
            answers = answers_of(run.output, dict(response.provider_details or {}))
        except (_BadAnswer, ValidationError) as e:
            return fail("bad_answer", e)
        judgment = Judgment.new(
            function=ask.function,
            subjects=subjects,
            model=response.model_name,
            state_sha256=input_sha256(state),
            bundle_sha256=ask.sha256,
            answers=answers,
            judged_at=now,
        )
        return Judged(output=run.output, judgment=judgment)


type Rule[OutputT: BaseModel] = Callable[[Judged[OutputT]], tuple[bool, float]]
"""Code policy over one judged result: (accept?, the combined score compared to thresholds).

It takes the whole Judged, not just the output, because a Score field arrives rounded to
its level while the policy wants the unrounded distribution — `position()` below reads it
from the stored answers.
"""


# Accessors over a stored Judgment. The reduction layer reads judgments back out of the
# store, where there is no filled output model to read a field from.


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


def certainty(judged: Judged[Any], keys: Collection[str] | None = None) -> float:
    """How sure the least sure of the named answers is, in [0, 1] (all of them by default).

    `keys` matters because one request can carry answers that decide different things: a
    field that rides along under its own policy must not drag the caller's confidence
    down. Computed from the stored distributions rather than read from the provider, so a
    judgment replayed from the store gives the same number. A Noul is its distance from
    0.5 doubled (0.5 = undecided); a Score or Choice is the probability of the level or
    option it landed on.
    """
    values = [
        abs(a.p_yes - 0.5) * 2.0 if isinstance(a, NoulAnswer) else max(a.probabilities)
        for a in judged.judgment.answers
        if keys is None or a.key in keys
    ]
    return min(values) if values else 0.0


def position(judged: Judged[Any], key: str) -> float:
    """A Score field's probability-weighted position in [0, 1] (lowest level = 0)."""
    return score(judged.judgment, key).expected_position


def level_probability(judged: Judged[Any], key: str, level: str) -> float:
    a = score(judged.judgment, key)
    return a.probabilities[a.levels.index(level)]


def choice_probability(judged: Judged[Any], key: str, option: str) -> float:
    a = choice(judged.judgment, key)
    return a.probabilities[a.options.index(option)]


def decide[OutputT: BaseModel](
    result: Judged[OutputT] | JevFailure,
    *,
    ask: Ask[OutputT],
    thresholds: tuple[Threshold, ...],
    rule: Rule[OutputT],
    policy: str | None = None,
) -> Decision:
    """Policy = ask.policy unless a variant policy is named (e.g. a fallback rule), and the
    identity includes ask.sha256. The result must come from this ask's wording (a mismatch
    is a wiring error and raises)."""
    if result.bundle_sha256 != ask.sha256:
        raise ValueError(f"result was produced by another ask than {ask.policy}")
    if isinstance(result, JevFailure):
        judgments: tuple[str, ...] = ()
        outcome: Literal["accept", "reject", "unjudged"] = "unjudged"
        value: float | None = None
    else:
        accept, value = rule(result)
        judgments = (result.judgment.id,)
        outcome = "accept" if accept else "reject"
    return Decision.new(
        function=result.function if isinstance(result, JevFailure) else result.judgment.function,
        subjects=result.subjects if isinstance(result, JevFailure) else result.judgment.subjects,
        policy=policy or ask.policy,
        bundle_sha256=ask.sha256,
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
