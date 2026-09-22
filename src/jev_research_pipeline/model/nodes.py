"""Pipeline types (packet "Build sequence" 2). Every type here is a JSON-LD node or value.

Flow the types encode (code owns control; Jev judges; Qwen writes):
    Line → QueryCandidate → SourceItem → Unit → Claim → Report ← Label
                 each Jev call → Judgment (raw probabilities) → Decision (code + thresholds)

Invariants are validated at construction and on load, so a store that parses is a
store that satisfies them. Each invariant is named in the comment above its check.
"""

from datetime import date
from typing import Annotated, ClassVar, Final, Literal, Self, override

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from .jsonld import IRI, Node, Sha256Hex, Value, content_id, kind_of, sha256_hex

type AdapterKind = Literal["arxiv", "hf_papers", "github", "web_search"]
"""Typed source adapters fixed in code per line (decision 4). X is a v1 non-goal."""

type JevFunction = Literal[
    "query_selection",
    "relevance_triage",
    "claim_detection",
    "novelty",
    "source_support",
    "source_trust",
    "report_ordering",
    "rubric_claim",
    "rubric_report",
]
"""One value per Jev row of the packet's judgment map."""

type RubricAxis = Literal["grounded", "relevant", "novel", "actionable"]
"""Per-claim rubric axes (the ones validated against gold)."""

type Probability = Annotated[float, Field(ge=0.0, le=1.0)]
type Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
type Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
type NonEmptyText = Annotated[str, StringConstraints(min_length=1)]
type NonNegInt = Annotated[int, Field(ge=0)]
type JevModel = Annotated[str, StringConstraints(pattern=r"^jev-\d+\.\d+\.\d+$")]
"""Exact version only: aliases drift and have no published deprecation policy (decision 9)."""

# Which store kinds each Jev function judges, in order. Pairs are ordered: source_support
# is (claim, source); rubric_claim is (claim, report) = the claim in its report's context.
SUBJECT_KINDS: Final[dict[str, tuple[str, ...]]] = {
    "query_selection": ("query",),
    "relevance_triage": ("source",),
    "claim_detection": ("unit",),
    "novelty": ("claim", "claim"),
    "source_support": ("claim", "source"),
    "source_trust": ("source",),
    "report_ordering": ("claim",),
    "rubric_claim": ("claim", "report"),
    "rubric_report": ("report",),
}

# Distributions from the API may be rounded; tolerate that much drift from 1.0.
_SUM_TOLERANCE: Final = 1e-3


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _all_kind(iris: tuple[str, ...], kind: str) -> bool:
    return all(kind_of(i) == kind for i in iris)


def _unique(items: tuple[str, ...]) -> bool:
    return len(set(items)) == len(items)


class StoreNode(Node):
    """A node minted by this pipeline. Invariant: @id == content_id(KIND, identity parts)."""

    def expected_id(self) -> str:
        raise NotImplementedError

    @model_validator(mode="after")
    def _id_is_content_derived(self) -> Self:
        expected = self.expected_id()
        _require(self.id == expected, f"@id {self.id} != content-derived {expected}")
        return self


# ---------------------------------------------------------------------------- Line


class Line(Node):
    """A research line. Its @id is the line graph's own @id, reused byte-identically so
    triples merge; the graph itself stays read-only (decision 2-3)."""

    type: Literal["Line"] = Field(
        default="Line", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "line"
    slug: Slug
    name: NonEmptyText
    adapters: tuple[AdapterKind, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        # The id comes from the line graph, never from the store namespace.
        _require(kind_of(self.id) is None, "Line @id must be the line graph's IRI, not a store IRI")
        _require(_unique(self.adapters), "adapters must be unique")
        return self


# ------------------------------------------------------------------ QueryCandidate


class QueryCandidate(StoreNode):
    """A search query proposed by Qwen (flash) for one adapter; Jev scores it, code keeps top-k."""

    type: Literal["QueryCandidate"] = Field(
        default="QueryCandidate", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "query"
    line: IRI
    adapter: AdapterKind
    text: NonEmptyText

    @staticmethod
    def id_for(line: str, adapter: str, text: str) -> str:
        return content_id("query", line, adapter, text)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.line, self.adapter, self.text)

    @classmethod
    def new(cls, *, line: str, adapter: AdapterKind, text: str) -> Self:
        return cls(id=cls.id_for(line, adapter, text), line=line, adapter=adapter, text=text)


# ---------------------------------------------------------------------- SourceItem


class SourceItem(StoreNode):
    """One fetched document. Identity = (line, url): refetching the same URL for the same
    line updates it in place; `content_sha256` tells whether the text changed."""

    type: Literal["SourceItem"] = Field(
        default="SourceItem", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "source"
    line: IRI
    adapter: AdapterKind
    url: IRI
    title: NonEmptyText
    text: str
    content_sha256: Sha256Hex
    fetched_at: AwareDatetime
    published_at: date | None = None

    @staticmethod
    def id_for(line: str, url: str) -> str:
        return content_id("source", line, url)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.line, self.url)

    @model_validator(mode="after")
    def _hash_matches_text(self) -> Self:
        _require(self.content_sha256 == sha256_hex(self.text), "content_sha256 does not match text")
        return self

    @classmethod
    def new(
        cls,
        *,
        line: str,
        adapter: AdapterKind,
        url: str,
        title: str,
        text: str,
        fetched_at: AwareDatetime,
        published_at: date | None = None,
    ) -> Self:
        return cls(
            id=cls.id_for(line, url),
            line=line,
            adapter=adapter,
            url=url,
            title=title,
            text=text,
            content_sha256=sha256_hex(text),
            fetched_at=fetched_at,
            published_at=published_at,
        )


# ---------------------------------------------------------------------------- Unit


class Unit(StoreNode):
    """A verbatim span [start, end) of one version of a source's text, cut by code.

    Invariant: text == source.text[start:end] for the source version whose hash is
    `source_sha256`. Only cut() creates units, so that holds by construction; on load
    the span length is checked here and matches() re-checks against a source.
    """

    type: Literal["Unit"] = Field(
        default="Unit", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "unit"
    source: IRI
    source_sha256: Sha256Hex
    start: NonNegInt
    end: NonNegInt
    granularity: Literal["sentence", "paragraph"]
    text: NonEmptyText

    @staticmethod
    def id_for(source: str, source_sha256: str, start: int, end: int) -> str:
        return content_id("unit", source, source_sha256, str(start), str(end))

    @override
    def expected_id(self) -> str:
        return self.id_for(self.source, self.source_sha256, self.start, self.end)

    @model_validator(mode="after")
    def _span(self) -> Self:
        _require(kind_of(self.source) == "source", "unit source must be a SourceItem IRI")
        _require(self.start < self.end, "span must be non-empty (start < end)")
        _require(len(self.text) == self.end - self.start, "span length != len(text)")
        _require(bool(self.text.strip()), "span must contain non-whitespace text")
        return self

    @classmethod
    def cut(
        cls,
        source: SourceItem,
        *,
        start: int,
        end: int,
        granularity: Literal["sentence", "paragraph"],
    ) -> Self:
        _require(0 <= start < end <= len(source.text), f"span [{start}, {end}) outside source text")
        return cls(
            id=cls.id_for(source.id, source.content_sha256, start, end),
            source=source.id,
            source_sha256=source.content_sha256,
            start=start,
            end=end,
            granularity=granularity,
            text=source.text[start:end],
        )

    def matches(self, source: SourceItem) -> bool:
        return (
            source.id == self.source
            and source.content_sha256 == self.source_sha256
            and source.text[self.start : self.end] == self.text
        )


# --------------------------------------------------------------------------- Claim


class Claim(StoreNode):
    """A unit accepted by claim detection. Claim = unit verbatim (no paraphrase), so
    quote-matching against the source is trivially true. `text` is a copy of the unit's
    text kept for store readability; from_unit() is the only constructor that sets it."""

    type: Literal["Claim"] = Field(
        default="Claim", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "claim"
    line: IRI
    unit: IRI
    text: NonEmptyText

    @staticmethod
    def id_for(unit: str) -> str:
        return content_id("claim", unit)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.unit)

    @model_validator(mode="after")
    def _unit_kind(self) -> Self:
        _require(kind_of(self.unit) == "unit", "claim unit must be a Unit IRI")
        return self

    @classmethod
    def from_unit(cls, unit: Unit, *, line: str) -> Self:
        return cls(id=cls.id_for(unit.id), line=line, unit=unit.id, text=unit.text)

    def matches(self, unit: Unit) -> bool:
        return unit.id == self.unit and unit.text == self.text


# ------------------------------------------------------------------------ Judgment


class NoulAnswer(Value):
    """Jev Noul: probability that the condition holds. 0.5 = undecided, not 'medium'."""

    kind: Literal["noul"] = "noul"
    key: Key
    p_yes: Probability


class ScoreAnswer(Value):
    """Jev Score: full distribution over ordered levels (low → high), kept raw."""

    kind: Literal["score"] = "score"
    key: Key
    levels: tuple[Key, ...] = Field(min_length=2)
    probabilities: tuple[Probability, ...]
    score: float | None = Field(default=None, ge=0.0)
    """Jev's unrounded position along the levels (0 .. len(levels)-1), as sent. Kept so a
    judgment replayed from the store rounds to the same level as the live answer did."""

    @model_validator(mode="after")
    def _distribution(self) -> Self:
        _require(_unique(self.levels), "levels must be unique")
        _require(len(self.levels) == len(self.probabilities), "levels and probabilities must align")
        _require(
            abs(sum(self.probabilities) - 1.0) <= _SUM_TOLERANCE, "probabilities must sum to 1"
        )
        return self

    @property
    def expected_position(self) -> float:
        """Probability-weighted level position scaled to [0, 1] (lowest = 0, highest = 1)."""
        last = len(self.levels) - 1
        return sum(p * i / last for i, p in enumerate(self.probabilities))


class ChoiceAnswer(Value):
    """Jev Choice: full distribution over unordered options, kept raw."""

    kind: Literal["choice"] = "choice"
    key: Key
    options: tuple[Key, ...] = Field(min_length=2)
    probabilities: tuple[Probability, ...]

    @model_validator(mode="after")
    def _distribution(self) -> Self:
        _require(_unique(self.options), "options must be unique")
        _require(
            len(self.options) == len(self.probabilities), "options and probabilities must align"
        )
        _require(
            abs(sum(self.probabilities) - 1.0) <= _SUM_TOLERANCE, "probabilities must sum to 1"
        )
        return self

    @property
    def argmax(self) -> str:
        return max(zip(self.options, self.probabilities, strict=True), key=lambda op: op[1])[0]


Answer = Annotated[NoulAnswer | ScoreAnswer | ChoiceAnswer, Field(discriminator="kind")]


class Judgment(StoreNode):
    """One Jev request: a bundle of narrow questions over one state, answers kept raw.

    Identity = (function, subjects, model, state hash, bundle hash): the same question
    bundle over the same state with the same pinned model is the same judgment, so a
    re-run reuses it. Judgments are facts from the model; thresholds live in Decision.
    """

    type: Literal["Judgment"] = Field(
        default="Judgment", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "judgment"
    function: JevFunction
    subjects: tuple[IRI, ...]
    model: JevModel
    state_sha256: Sha256Hex
    bundle_sha256: Sha256Hex
    answers: tuple[Answer, ...] = Field(min_length=1)
    judged_at: AwareDatetime

    @staticmethod
    def id_for(
        function: str, subjects: tuple[str, ...], model: str, state_sha256: str, bundle_sha256: str
    ) -> str:
        return content_id("judgment", function, *subjects, model, state_sha256, bundle_sha256)

    @override
    def expected_id(self) -> str:
        return self.id_for(
            self.function, self.subjects, self.model, self.state_sha256, self.bundle_sha256
        )

    @model_validator(mode="after")
    def _shape(self) -> Self:
        want = SUBJECT_KINDS[self.function]
        got = tuple(kind_of(s) for s in self.subjects)
        _require(got == want, f"subjects for {self.function} must be kinds {want}, got {got}")
        _require(_unique(tuple(a.key for a in self.answers)), "answer keys must be unique")
        return self

    @classmethod
    def new(
        cls,
        *,
        function: JevFunction,
        subjects: tuple[str, ...],
        model: str,
        state_sha256: str,
        bundle_sha256: str,
        answers: tuple[Answer, ...],
        judged_at: AwareDatetime,
    ) -> Self:
        return cls(
            id=cls.id_for(function, subjects, model, state_sha256, bundle_sha256),
            function=function,
            subjects=subjects,
            model=model,
            state_sha256=state_sha256,
            bundle_sha256=bundle_sha256,
            answers=answers,
            judged_at=judged_at,
        )

    def answer(self, key: str) -> Answer:
        for a in self.answers:
            if a.key == key:
                return a
        raise KeyError(key)


# ------------------------------------------------------------------------ Decision


class Threshold(Value):
    """One threshold/weight value as applied — recorded so a refit can be replayed."""

    name: Key
    value: float


class Decision(StoreNode):
    """What code decided from judgments + a threshold policy.

    Invariant (failure policy, decision 8): outcome "unjudged" ⇔ no judgments ⇔ no score.
    A Jev timeout/error becomes "unjudged" and goes to the report's unjudged section; it
    never fails open into accept.
    """

    type: Literal["Decision"] = Field(
        default="Decision", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "decision"
    function: JevFunction
    subjects: tuple[IRI, ...]
    policy: NonEmptyText
    bundle_sha256: Sha256Hex
    """The question bundle's wording hash. Part of the identity: rewording a bundle (even
    without a version bump) makes new Decisions instead of overwriting old ones."""
    judgments: tuple[IRI, ...]
    thresholds: tuple[Threshold, ...]
    outcome: Literal["accept", "reject", "unjudged"]
    score: float | None
    """The combined value code compared against the thresholds."""

    @staticmethod
    def id_for(function: str, subjects: tuple[str, ...], policy: str, bundle_sha256: str) -> str:
        return content_id("decision", function, *subjects, policy, bundle_sha256)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.function, self.subjects, self.policy, self.bundle_sha256)

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        want = SUBJECT_KINDS[self.function]
        got = tuple(kind_of(s) for s in self.subjects)
        _require(got == want, f"subjects for {self.function} must be kinds {want}, got {got}")
        _require(_all_kind(self.judgments, "judgment"), "judgments must be Judgment IRIs")
        _require(_unique(tuple(t.name for t in self.thresholds)), "threshold names must be unique")
        if self.outcome == "unjudged":
            _require(
                not self.judgments and self.score is None, "unjudged has no judgments and no score"
            )
        else:
            _require(bool(self.judgments), "a judged decision needs at least one judgment")
            _require(self.score is not None, "a judged decision needs a score")
        return self

    @classmethod
    def new(
        cls,
        *,
        function: JevFunction,
        subjects: tuple[str, ...],
        policy: str,
        bundle_sha256: str,
        judgments: tuple[str, ...],
        thresholds: tuple[Threshold, ...],
        outcome: Literal["accept", "reject", "unjudged"],
        score: float | None,
    ) -> Self:
        return cls(
            id=cls.id_for(function, subjects, policy, bundle_sha256),
            function=function,
            subjects=subjects,
            policy=policy,
            bundle_sha256=bundle_sha256,
            judgments=judgments,
            thresholds=thresholds,
            outcome=outcome,
            score=score,
        )


# -------------------------------------------------------------------------- Report


class AxisMeter(Value):
    """Rubric axis for one report: mean Jev score and agreement with gold (None = no ticks yet)."""

    axis: RubricAxis
    mean_score: Probability | None
    """None = no rubric judgment that day (distinct from a 0.0 = worst score)."""
    gold_agreement: Probability | None


class Operations(Value):
    """The operations section every report ends with (decisions 7-8)."""

    jev_questions: NonNegInt
    generation_input_tokens: NonNegInt
    generation_output_tokens: NonNegInt
    claude_calls: Literal[0]
    """Non-goal: Claude at runtime. The meter exists to prove it stays 0."""
    cost_usd: Annotated[float, Field(ge=0.0)]
    rubric: tuple[AxisMeter, ...]
    fill_rate_previous: Probability | None
    """Primary success metric, measured on the previous report (ticks arrive after reading)."""

    @model_validator(mode="after")
    def _axes_unique(self) -> Self:
        _require(_unique(tuple(m.axis for m in self.rubric)), "rubric axes must be unique")
        return self


class Report(StoreNode):
    """One line-run's report. Identity = (line, run_date): one report per line per day,
    so a same-day re-run overwrites instead of duplicating.

    Invariants: rendering "template" ⇔ prose is None (Qwen synthesis failed or rubric
    stayed low after one rewrite); `claims` is the reading order and holds only claims,
    each once; `unjudged` never overlaps `claims` (no fail-open into the body).
    """

    type: Literal["Report"] = Field(
        default="Report", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "report"
    line: IRI
    run_date: date
    rendering: Literal["prose", "rewritten", "template"]
    prose: str | None
    claims: tuple[IRI, ...]
    unjudged: tuple[IRI, ...]
    partial: bool
    """True when the cost cap cut the run short."""
    operations: Operations

    @staticmethod
    def id_for(line: str, run_date: date) -> str:
        return content_id("report", line, run_date.isoformat())

    @override
    def expected_id(self) -> str:
        return self.id_for(self.line, self.run_date)

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        _require(
            (self.rendering == "template") == (self.prose is None),
            "template rendering ⇔ prose is None",
        )
        _require(_all_kind(self.claims, "claim"), "claims must be Claim IRIs")
        _require(_unique(self.claims), "claims must be unique")
        _require(not set(self.unjudged) & set(self.claims), "unjudged must not overlap claims")
        return self

    @classmethod
    def new(
        cls,
        *,
        line: str,
        run_date: date,
        rendering: Literal["prose", "rewritten", "template"],
        prose: str | None,
        claims: tuple[str, ...],
        unjudged: tuple[str, ...],
        partial: bool,
        operations: Operations,
    ) -> Self:
        return cls(
            id=cls.id_for(line, run_date),
            line=line,
            run_date=run_date,
            rendering=rendering,
            prose=prose,
            claims=claims,
            unjudged=unjudged,
            partial=partial,
            operations=operations,
        )


# --------------------------------------------------------------------------- Label


class Label(StoreNode):
    """Gold label = the author's ⭕❌ tick on a claim in a report, harvested from the vault.

    Only gold is stored. Silver labels (validated rubric axes on unticked claims) are
    derived at fit time from rubric Judgments, never persisted as Labels (decision 5).
    Identity = (claim, report): re-harvesting overwrites with the latest tick state.
    """

    type: Literal["Label"] = Field(
        default="Label", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "label"
    claim: IRI
    report: IRI
    verdict: Literal["correct", "incorrect"]
    harvested_at: AwareDatetime

    @staticmethod
    def id_for(claim: str, report: str) -> str:
        return content_id("label", claim, report)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.claim, self.report)

    @model_validator(mode="after")
    def _kinds(self) -> Self:
        _require(kind_of(self.claim) == "claim", "label claim must be a Claim IRI")
        _require(kind_of(self.report) == "report", "label report must be a Report IRI")
        return self

    @classmethod
    def new(
        cls,
        *,
        claim: str,
        report: str,
        verdict: Literal["correct", "incorrect"],
        harvested_at: AwareDatetime,
    ) -> Self:
        return cls(
            id=cls.id_for(claim, report),
            claim=claim,
            report=report,
            verdict=verdict,
            harvested_at=harvested_at,
        )


# ------------------------------------------------------ pipeline state (not research data)


class RotationCursor(StoreNode):
    """Where the line rotation resumes. Singleton: its @id is constant, so every write
    replaces the previous cursor. Holds the next line's slug rather than an index, so
    reordering or extending the config order never shifts which line runs next."""

    type: Literal["RotationCursor"] = Field(
        default="RotationCursor", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "cursor"
    next_slug: Slug | None
    """None = start at the head of the configured order."""
    updated_at: AwareDatetime

    @staticmethod
    def id_for() -> str:
        return content_id("cursor", "rotation")

    @override
    def expected_id(self) -> str:
        return self.id_for()

    @classmethod
    def new(cls, *, next_slug: str | None, updated_at: AwareDatetime) -> Self:
        return cls(id=cls.id_for(), next_slug=next_slug, updated_at=updated_at)


class StageRecord(StoreNode):
    """A completed pipeline stage: (stage, input content hash) → the store @ids it produced.

    Identity = (stage, input_sha256), so the same input to the same stage is done once
    (decision 8). `outputs` may be empty: a stage that ran and produced nothing is done.
    """

    type: Literal["StageRecord"] = Field(
        default="StageRecord", validation_alias="@type", serialization_alias="@type"
    )
    KIND: ClassVar[str] = "stage"
    stage: Key
    input_sha256: Sha256Hex
    outputs: tuple[IRI, ...]
    completed_at: AwareDatetime

    @staticmethod
    def id_for(stage: str, input_sha256: str) -> str:
        return content_id("stage", stage, input_sha256)

    @override
    def expected_id(self) -> str:
        return self.id_for(self.stage, self.input_sha256)

    @model_validator(mode="after")
    def _outputs(self) -> Self:
        _require(
            all(kind_of(o) is not None for o in self.outputs), "outputs must be store node IRIs"
        )
        _require(_unique(self.outputs), "outputs must be unique")
        return self

    @classmethod
    def new(
        cls,
        *,
        stage: str,
        input_sha256: str,
        outputs: tuple[str, ...],
        completed_at: AwareDatetime,
    ) -> Self:
        return cls(
            id=cls.id_for(stage, input_sha256),
            stage=stage,
            input_sha256=input_sha256,
            outputs=outputs,
            completed_at=completed_at,
        )


GraphNodeType = (
    Line
    | QueryCandidate
    | SourceItem
    | Unit
    | Claim
    | Judgment
    | Decision
    | Report
    | Label
    | RotationCursor
    | StageRecord
)
GraphNode = Annotated[GraphNodeType, Field(discriminator="type")]
