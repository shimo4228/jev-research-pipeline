"""JSON-LD scheme for the pipeline store: @id recipe, @context, node base class.

Store = JSON-LD content graph owned by this pipeline (packet decision 3). It never
writes into a line's graph.jsonld; it merges with it by reusing the line's @id
byte-identically (Line.id) and minting its own nodes under STORE_NS.

@id recipe (invariant, enforced in every store node's validator):
    STORE_NS + "<kind>/" + sha256("\\x1f".join(parts))[:32]
The parts are the node's identity fields, so the same content always yields the same
@id — this is what makes stage outputs idempotent (packet decision 8).
"""

import hashlib
import re
from typing import Annotated, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Owner vocab namespace per skill: jsonld-knowledge-graph (`https://<owner>.github.io/<owner>/vocab#`).
VOCAB_NS: Final = "https://shimo4228.github.io/shimo4228/vocab#jrp/"
# Store node IRIs are identifiers, not dereferenceable documents.
STORE_NS: Final = "https://shimo4228.github.io/shimo4228/jrp/"

# \x1f (unit separator) cannot occur in IRIs, hex digests or decimal offsets, so
# ("ab", "c") and ("a", "bc") never collide.
_PART_SEP: Final = "\x1f"
_KIND_RE: Final = re.compile(rf"^{re.escape(STORE_NS)}([a-z_]+)/[0-9a-f]{{32}}$")

type IRI = Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
type Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_id(kind: str, *parts: str) -> str:
    """Store @id for a node of `kind` whose identity fields are `parts`."""
    digest = sha256_hex(_PART_SEP.join(parts))[:32]
    return f"{STORE_NS}{kind}/{digest}"


def kind_of(iri: str) -> str | None:
    """The `kind` segment of a store @id, or None for IRIs outside the store (e.g. a line)."""
    m = _KIND_RE.match(iri)
    return m.group(1) if m else None


def _iri(term: str) -> dict[str, str]:
    return {"@id": f"{VOCAB_NS}{term}", "@type": "@id"}


def _iri_list(term: str) -> dict[str, str]:
    return {"@id": f"{VOCAB_NS}{term}", "@type": "@id", "@container": "@list"}


def _list(term: str) -> dict[str, str]:
    return {"@id": f"{VOCAB_NS}{term}", "@container": "@list"}


def _typed(term: str, xsd: str) -> dict[str, str]:
    return {"@id": f"{VOCAB_NS}{term}", "@type": f"xsd:{xsd}"}


# Fields whose values are IRIs. Without "@type": "@id" a JSON-LD processor reads them
# as string literals and the cross-graph join silently disappears (URL-LITERAL).
IRI_FIELDS: Final = frozenset(
    {
        "line",
        "url",
        "source",
        "unit",
        "subjects",
        "judgments",
        "claims",
        "unjudged",
        "claim",
        "report",
        "outputs",
    }
)
# Fields whose order carries meaning. JSON-LD arrays are unordered sets unless @list.
ORDERED_FIELDS: Final = frozenset({"subjects", "claims", "levels", "options", "probabilities"})

# The single @context of every store document. from_document() rejects any other, so a
# change here is a store format change (bump deliberately, migrate the store).
CONTEXT: Final[dict[str, str | dict[str, str]]] = {
    "@vocab": VOCAB_NS,
    "schema": "https://schema.org/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    # identity / provenance
    "slug": f"{VOCAB_NS}slug",
    "name": "schema:name",
    "title": "schema:headline",
    "text": "schema:text",
    "url": {"@id": "schema:url", "@type": "@id"},
    "line": _iri("line"),
    "adapter": f"{VOCAB_NS}adapter",
    "adapters": f"{VOCAB_NS}adapters",
    "source": _iri("source"),
    "unit": _iri("unit"),
    "claim": _iri("claim"),
    "report": _iri("report"),
    "content_sha256": f"{VOCAB_NS}contentSha256",
    "source_sha256": f"{VOCAB_NS}sourceSha256",
    "fetched_at": _typed("fetchedAt", "dateTime"),
    "published_at": _typed("publishedAt", "date"),
    "start": _typed("start", "integer"),
    "end": _typed("end", "integer"),
    "granularity": f"{VOCAB_NS}granularity",
    # judgment
    "kind": f"{VOCAB_NS}kind",
    "function": f"{VOCAB_NS}function",
    "subjects": _iri_list("subjects"),
    "model": f"{VOCAB_NS}model",
    "state_sha256": f"{VOCAB_NS}stateSha256",
    "bundle_sha256": f"{VOCAB_NS}bundleSha256",
    "answers": f"{VOCAB_NS}answers",
    "key": f"{VOCAB_NS}key",
    "p_yes": _typed("pYes", "double"),
    "levels": _list("levels"),
    "options": _list("options"),
    "probabilities": _list("probabilities"),
    "judged_at": _typed("judgedAt", "dateTime"),
    # decision
    "policy": f"{VOCAB_NS}policy",
    "judgments": _iri("judgments"),
    "thresholds": f"{VOCAB_NS}thresholds",
    "value": _typed("value", "double"),
    "outcome": f"{VOCAB_NS}outcome",
    "score": _typed("score", "double"),
    # label
    "verdict": f"{VOCAB_NS}verdict",
    "harvested_at": _typed("harvestedAt", "dateTime"),
    # report
    "run_date": _typed("runDate", "date"),
    "rendering": f"{VOCAB_NS}rendering",
    "prose": f"{VOCAB_NS}prose",
    "claims": _iri_list("claims"),
    "unjudged": _iri("unjudged"),
    "partial": f"{VOCAB_NS}partial",
    "operations": f"{VOCAB_NS}operations",
    "jev_questions": _typed("jevQuestions", "integer"),
    "generation_input_tokens": _typed("generationInputTokens", "integer"),
    "generation_output_tokens": _typed("generationOutputTokens", "integer"),
    "claude_calls": _typed("claudeCalls", "integer"),
    "cost_usd": _typed("costUsd", "double"),
    "rubric": f"{VOCAB_NS}rubric",
    "axis": f"{VOCAB_NS}axis",
    "mean_score": _typed("meanScore", "double"),
    "gold_agreement": _typed("goldAgreement", "double"),
    "fill_rate_previous": _typed("fillRatePrevious", "double"),
    # pipeline state
    "next_slug": f"{VOCAB_NS}nextSlug",
    "updated_at": _typed("updatedAt", "dateTime"),
    "stage": f"{VOCAB_NS}stage",
    "input_sha256": f"{VOCAB_NS}inputSha256",
    "outputs": _iri("outputs"),
    "completed_at": _typed("completedAt", "dateTime"),
}


class Value(BaseModel):
    """Nested value object (a blank node in JSON-LD). Immutable, closed schema.
    NaN/inf are rejected: they are not JSON and would corrupt the store file."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Node(BaseModel):
    """A top-level graph node. `id` ↔ "@id", `type` ↔ "@type" on the wire.

    Subclasses pin `type` to a Literal equal to their class name; that Literal is the
    discriminator from_document() dispatches on. NaN/inf are rejected (see Value).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    id: IRI = Field(validation_alias="@id", serialization_alias="@id")
    KIND: ClassVar[str]
