"""Jev core: one Pydantic output model per function, called through pydantic-ai's typesafe model.

Migrated 2026-09-23 from a hand-rolled bundle layer: the same abstraction now drives both
models the pipeline uses, and the questions live on the types instead of in a parallel
structure that had to be converted.

One Jev use = one output model over one state in one request — or, for the screen, one
output model per slot over several subjects in one request (judge_batch), each subject
still stored as its own Judgment. A field is one question —
`float` bounded 0..1 is a Noul and comes back as the raw probability, a `Literal` is a
Choice, an `IntEnum` with a docstring per member is a Score. Code owns everything around
it: the state, the thresholds and the Decision. A failed request never raises into the
pipeline — it becomes a JevFailure, and decide() turns that into an "unjudged" Decision.

Trade-off of the migration: a Noul's true/false criteria collapse into one field
description, so both sides of the condition have to be written into the question itself.
"""

import asyncio
import copy
import functools
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Annotated, Any, Final, Literal, TypeAliasType, cast, get_args, get_origin

import httpx2
from pydantic import AwareDatetime, BaseModel, Field, JsonValue, ValidationError, create_model
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

JEV_REQUESTS_PER_MINUTE: Final = 1200
"""Published rate limit for jev-1.13.0 (docs.typesafe.ai models, as-of 2026-09-23; the page
says limits adjust dynamically). The SDK's own retries on 429 are not counted here."""

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

    def batched(self, subject: str) -> "Ask[OutputT]":
        """The same questions asked of several `subject`s in one request (judge_batch).

        Its own ask: the instructions say how a slot maps onto the state, so its sha and
        policy differ from the single request's, and a batched answer is never stored as
        if it had been asked alone. The output stays the one-subject model — that is what
        each slot is read back into, and what a stored Judgment replays as."""
        return Ask(
            function=self.function,
            version=f"{self.version}_batch",
            output=self.output,
            instructions=self.instructions.replace(f"`{subject}`", f"every `{subject}s.sN`")
            + "\n\n"
            + _BATCH_NOTE.format(subject=subject),
        )


_BATCH_NOTE: Final = (
    "Several {subject}s are judged at once. `{subject}s` holds them under the slot names "
    "s0, s1, and so on. A question whose field is `sN.<name>` is about `{subject}s.sN` "
    "alone and names it that way; judge every slot on its own, the other slots are not "
    "context for it."
)

BATCH_SUBJECT: Final = "source"
"""What every batched ask varies: the pipeline batches sources, never questions or claims."""

BATCH_MAX_ITEMS: Final = 1
"""Subjects per batched request. 1 = every request judges one subject: the slot bleed
check (scratch run 3, 2026-09-23, docs/pilot-log.md) found batched and single routes
agreeing on 11 of 20 (source, question) pairs, the batch inflating on_topic (a radiomics
paper kept for a Jev calibration question). The judge's bar was 90%; the batching stays
in place for a re-test, switched off here."""
BATCH_STATE_TOKENS: Final = 24_000
"""Estimated state size a batch may reach. The limit is 32k tokens for the state plus the
longest question and 64k per request (docs.typesafe.ai models, as-of 2026-09-23); the
margin absorbs the estimate's error and the longest question."""


def estimated_tokens(value: JsonValue) -> int:
    """A deliberately high guess: one token per three UTF-8 bytes. A CJK character is three
    bytes and about one token; English runs about four characters a token."""
    return len(json.dumps(value, ensure_ascii=False).encode()) // 3 + 1


def batches(
    states: Sequence[JevState], subject: str, *, max_items: int = BATCH_MAX_ITEMS
) -> list[list[int]]:
    """Indices of `states`, cut greedily into batches that stay within BATCH_MAX_ITEMS
    and BATCH_STATE_TOKENS (the shared part counted once). An item too big for any
    batch goes alone — as big as a single request would have sent anyway."""
    if not states:
        return []
    shared = estimated_tokens({k: v for k, v in states[0].items() if k != subject})
    out: list[list[int]] = []
    current: list[int] = []
    tokens = shared
    for i, state in enumerate(states):
        size = estimated_tokens(state[subject])
        if current and (len(current) >= max_items or tokens + size > BATCH_STATE_TOKENS):
            out.append(current)
            current, tokens = [], shared
        current.append(i)
        tokens += size
    out.append(current)
    return out


@functools.cache
def batch_output(ask: Ask[Any], subject: str, n: int) -> type[BaseModel]:
    """The output model of an n-subject request: one nested slot model per subject, each
    field's question rewritten to name its own slot (`source` → `sources.s3`) so no
    question can be read as being about another slot's subject."""
    doc = (ask.output.__doc__ or "").strip()

    def slot(i: int) -> type[BaseModel]:
        fields: dict[str, Any] = {}
        for name, info in ask.output.model_fields.items():
            renamed = copy.copy(info)
            renamed.description = (info.description or "").replace(
                f"`{subject}`", f"`{subject}s.s{i}`"
            )
            fields[name] = (info.annotation, renamed)
        return create_model(f"{ask.output.__name__}S{i}", __doc__=doc, **fields)

    slots: dict[str, Any] = {
        f"s{i}": (slot(i), Field(description=f"`{subject}s.s{i}`")) for i in range(n)
    }
    return create_model(
        f"{ask.output.__name__}Batch",
        __doc__=f"{doc} Asked once per slot of `{subject}s`.",
        **slots,
    )


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


class RequestPacer:
    """At most `per_minute` requests in any 60 s window, however many tasks ask at once.

    The window and the wait are read under one lock: two tasks that both saw a free slot
    would otherwise both send. The clock and the sleep are injectable for tests.
    """

    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.per_minute = per_minute
        self._clock, self._sleep = clock, sleep
        self._sent: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def admit(self) -> None:
        async with self._lock:
            now = self._clock()
            while self._sent and now - self._sent[0] >= 60.0:
                self._sent.popleft()
            if len(self._sent) >= self.per_minute:
                await self._sleep(60.0 - (now - self._sent[0]))
                self._sent.popleft()
                now = self._clock()
            self._sent.append(now)


@dataclass(frozen=True)
class _Sent[OutputT: BaseModel]:
    """What one request brought back, before it is split into per-subject Judgments."""

    output: OutputT
    model: str
    details: dict[str, Any]


@dataclass(frozen=True)
class _Refused:
    reason: FailureReason
    detail: str
    splittable: bool
    """A batch that failed for this reason may succeed in halves, because one item can be
    the cause: a malformed answer, or a request too big (413, or a 400/422 that says
    max_tokens). Everything else fails every half the same way — a bad key (401/403), a
    timeout, 408/429, 5xx — so splitting would only multiply requests that fail."""


def _size_refusal(e: ModelHTTPError) -> bool:
    return e.status_code == 413 or (
        e.status_code in (400, 422) and "max_tokens" in f"{e.body} {e.message}"
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
        self.pacer = RequestPacer(JEV_REQUESTS_PER_MINUTE)

    async def aclose(self) -> None:
        """The HTTP client is owned by the caller; nothing of ours outlives a run."""

    @staticmethod
    def _check_subjects(function: JevFunction, subjects: tuple[str, ...]) -> None:
        # Wiring errors are programming errors: raise before any request, never "unjudged".
        want = SUBJECT_KINDS[function]
        got = tuple(kind_of(s) for s in subjects)
        if got != want:
            raise ValueError(f"subjects for {function} must be kinds {want}, got {got}")

    async def judge[OutputT: BaseModel](
        self,
        ask: Ask[OutputT],
        subjects: tuple[str, ...],
        state: JevState,
        *,
        now: AwareDatetime,
    ) -> Judged[OutputT] | JevFailure:
        self._check_subjects(ask.function, subjects)
        questions = len(ask.output.model_fields)
        # Counted before the first await, so a concurrent task that checks the cost cap
        # right after this one was admitted already sees what it is about to spend.
        self.questions_asked += questions
        with span(
            f"jev.{ask.function}",
            function=ask.function,
            questions=questions,
            subjects=len(subjects),
            model=JEV_MODEL,
        ) as current:
            sent = await self._send(ask.output, ask.instructions, state)
            result = (
                _failure(ask, subjects, sent)
                if isinstance(sent, _Refused)
                else _judged(ask, subjects, state, sent.output, sent, now=now)
            )
            current.set_attribute(
                "jrp.outcome", "judged" if isinstance(result, Judged) else result.reason
            )
            return result

    async def judge_batch[OutputT: BaseModel](
        self,
        ask: Ask[OutputT],
        items: Sequence[tuple[tuple[str, ...], JevState]],
        *,
        subject: str,
        now: AwareDatetime,
    ) -> list[Judged[OutputT] | JevFailure]:
        """Several subjects of one ask in one request: `items` are (subjects, the state a
        single request would send), and the states differ only under `subject`.

        The request carries the shared part once and the items under `<subject>s.sN`;
        each field is asked once per slot (`sN.<field>`, pydantic-ai's nested naming). Every
        item still gets its own Judgment, keyed by its single-request state — so a stored
        answer is found again whatever batch the item lands in next time. One item is a
        plain judge(): a batch of one is today's request, byte for byte. A batch that
        fails for a reason inside it is split in halves until the item at fault stands
        alone as the only "unjudged" one.
        """
        if len(items) <= 1:
            return [await self.judge(ask, subjects, state, now=now) for subjects, state in items]
        shared = _without(items[0][1], subject)
        for subjects, state in items:
            self._check_subjects(ask.function, subjects)
            if _without(state, subject) != shared:
                raise ValueError(f"batched states must differ only under {subject!r}")
        batch = ask.batched(subject)
        questions = len(ask.output.model_fields) * len(items)
        self.questions_asked += questions
        with span(
            f"jev.{ask.function}",
            function=ask.function,
            questions=questions,
            subjects=len(items),
            model=JEV_MODEL,
            batch=len(items),
        ) as current:
            state: JevState = {
                **shared,
                f"{subject}s": {f"s{i}": st[subject] for i, (_, st) in enumerate(items)},
            }
            sent = await self._send(
                batch_output(ask, subject, len(items)), batch.instructions, state
            )
            current.set_attribute(
                "jrp.outcome", sent.reason if isinstance(sent, _Refused) else "judged"
            )
        if isinstance(sent, _Refused):
            if not sent.splittable:
                return [_failure(batch, subjects, sent) for subjects, _ in items]
            half = len(items) // 2
            return [
                *await self.judge_batch(ask, items[:half], subject=subject, now=now),
                *await self.judge_batch(ask, items[half:], subject=subject, now=now),
            ]
        out: list[Judged[OutputT] | JevFailure] = []
        for i, (subjects, st) in enumerate(items):
            slot = f"s{i}"
            try:
                output = ask.output.model_validate(getattr(sent.output, slot).model_dump())
            except ValidationError as e:
                out.append(
                    _failure(
                        batch,
                        subjects,
                        _Refused(reason="bad_answer", detail=str(e), splittable=False),
                    )
                )
                continue
            one = _Sent[OutputT](
                output=output, model=sent.model, details=_slot_details(sent.details, slot)
            )
            out.append(_judged(batch, subjects, st, output, one, now=now))
        return out

    async def _send[OutputT: BaseModel](
        self, output: type[OutputT], instructions: str, state: JevState
    ) -> "_Sent[OutputT] | _Refused":
        await self.pacer.admit()
        agent = Agent(
            self._model,
            output_type=output,
            instructions=instructions,
            model_settings=self._settings,
        )
        try:
            run = await agent.run(json.dumps(state, ensure_ascii=False, sort_keys=True))
        except ModelHTTPError as e:
            return _Refused(reason="api_error", detail=str(e), splittable=_size_refusal(e))
        except UnexpectedModelBehavior as e:
            return _Refused(reason="bad_answer", detail=str(e), splittable=True)
        except ModelAPIError as e:
            # The SDK's timeout is a connection error; only the cause tells them apart.
            reason: FailureReason = (
                "timeout" if isinstance(e.__cause__, TimeoutError) else "connection"
            )
            return _Refused(reason=reason, detail=str(e), splittable=False)
        response: ModelResponse = run.response
        if response.model_name != JEV_MODEL:
            return _Refused(
                reason="model_mismatch",
                detail=f"asked {JEV_MODEL}, answered by {response.model_name}",
                splittable=False,
            )
        return _Sent[OutputT](
            output=run.output,
            model=response.model_name,
            details=dict(response.provider_details or {}),
        )


def _without(state: JevState, key: str) -> JevState:
    return {k: v for k, v in state.items() if k != key}


def _slot_details(details: dict[str, Any], slot: str) -> dict[str, Any]:
    """One slot's share of provider_details, with its `sN.` prefix taken off — the shape
    a single request's details have, so answers_of() reads it unchanged."""
    prefix = f"{slot}."
    out: dict[str, Any] = {}
    for kind, per_field in details.items():
        if isinstance(per_field, dict):
            fields = cast(dict[str, Any], per_field)
            out[kind] = {
                k.removeprefix(prefix): v for k, v in fields.items() if k.startswith(prefix)
            }
    return out


def _failure(ask: Ask[Any], subjects: tuple[str, ...], refused: _Refused) -> JevFailure:
    return JevFailure(
        function=ask.function,
        subjects=subjects,
        bundle_sha256=ask.sha256,
        reason=refused.reason,
        detail=refused.detail,
    )


def _judged[OutputT: BaseModel](
    ask: Ask[Any],
    subjects: tuple[str, ...],
    state: JevState,
    output: OutputT,
    sent: _Sent[Any],
    *,
    now: AwareDatetime,
) -> Judged[OutputT] | JevFailure:
    try:
        # TypeError is not caught: an output field Jev cannot be asked about is a
        # wiring error, and swallowing it would make every subject pay for a request
        # whose Decision is "unjudged" forever.
        answers = answers_of(output, sent.details)
    except (_BadAnswer, ValidationError) as e:
        return _failure(
            ask, subjects, _Refused(reason="bad_answer", detail=str(e), splittable=False)
        )
    judgment = Judgment.new(
        function=ask.function,
        subjects=subjects,
        model=sent.model,
        state_sha256=input_sha256(state),
        bundle_sha256=ask.sha256,
        answers=answers,
        judged_at=now,
    )
    return Judged(output=output, judgment=judgment)


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
    """Policy = the asking ask's policy unless a variant policy is named (e.g. a fallback
    rule), and the identity includes its sha256. The result must come from this ask's
    wording, asked alone or batched over sources (anything else is a wiring error)."""
    if result.bundle_sha256 != ask.sha256:
        ask = ask.batched(BATCH_SUBJECT)
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
