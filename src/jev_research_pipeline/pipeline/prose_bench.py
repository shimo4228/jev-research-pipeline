"""Prose bench: frozen question-day inputs, prompt/model variants, blind pairs for a judge.

The one generation site left is the prose (design "Authored queries"), and the author's
verdict on it is "weak". This is the loop that improves it without touching a run:

    jrp prose export   question-days with prose, from one or more stores → frozen cases
    jrp prose bench    one variant (prompt file x model x thinking x material) over the
                       cases → drafts, each with the code gates (facts, not taste)
    jrp prose pairs    two variants → one blind pair file per (case, order), the rubric
                       inside with its axes shuffled, and a key the judge never sees
    jrp prose tally    the judge's verdict files + the key → per-axis wins and ties

The judge is a fresh-context Opus run from the author's Claude session, reading one pair
file and writing one verdict file (docs/prose-rubric.md) — dev time only; no run calls
Claude. Everything lives under <JRP_STORE_DIR>/prose_bench/, never in the repo: cases
carry verbatim third-party text (claims, source excerpts), and the repo is public.

Cases are split by their id alone (about one in three held out), so a case never changes
side when later exports add cases. Variants are tuned on `dev` and accepted only if `holdout` does not get worse.
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final, Literal

import httpx2
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.alibaba import AlibabaProvider

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import (
    Claim,
    GraphNodeType,
    Line,
    Question,
    QuestionLog,
    Report,
    SourceItem,
    Unit,
)
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.qwen import GenerationMeter
from jev_research_pipeline.qwen.client import (
    DASHSCOPE_BASE_URL,
    NO_THINKING,
    THINKING,
    _native_json_schema,  # pyright: ignore[reportPrivateUsage]
)
from jev_research_pipeline.qwen.prose import (
    INFERENCE_MARK,
    NO_DIRECT_EVIDENCE,
    PROSE_TIMEOUT_S,
    write_prose,
)
from jev_research_pipeline.store import GraphStore

BENCH_DIR: Final = "prose_bench"
EXCERPT_CHARS: Final = 1500
"""Per source: enough of an abstract to say what the work did and on what."""
HOLDOUT_EVERY: Final = 3

type Split = Literal["dev", "holdout"]


class BenchSource(Value):
    title: str
    url: str
    excerpt: str


class BenchClaim(Value):
    text: str
    source: int | None
    """1-based index into BenchCase.sources, None when the claim's source is not stored."""


class BenchCase(Value):
    id: str
    split: Split
    line_slug: str
    line_name: str
    vocabulary: tuple[str, ...]
    question_title: str
    question_brief: str
    run_date: date
    claims: tuple[BenchClaim, ...]
    known: tuple[str, ...]
    sources: tuple[BenchSource, ...]
    baseline: str
    """The prose the run actually wrote that day — a reference, not a variant."""


class Draft(Value):
    case: str
    variant: str
    prose: str | None
    failure: str | None
    seconds: float
    chars: int
    gates: tuple[str, ...]
    """Code-gate failures; empty = passed. Facts only (citations, marks), never taste."""


@dataclass(frozen=True)
class Variant:
    name: str
    instructions: str
    model: str
    thinking: bool
    sources: bool
    """Send source titles and excerpts with the claims (thicker material)."""


def bench_dir(store_root: Path) -> Path:
    return store_root / BENCH_DIR


# --- export ---------------------------------------------------------------------------------


def _case_id(line: str, question: str, claims: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps([line, question, list(claims)]).encode()).hexdigest()[:12]


def cases_from_nodes(
    slug: str, nodes: Mapping[str, GraphNodeType], *, line_name: str, vocabulary: Sequence[str]
) -> list[BenchCase]:
    """Every question-day with prose in one line partition. `split` is assigned later."""
    out: list[BenchCase] = []
    reports = [n for n in nodes.values() if isinstance(n, Report)]
    for log in (n for n in nodes.values() if isinstance(n, QuestionLog) and n.text):
        question = nodes.get(log.question)
        claims = [c for i in log.claims if isinstance(c := nodes.get(i), Claim)]
        if not isinstance(question, Question) or not claims:
            continue
        sources: list[SourceItem] = []
        claim_sources: list[int | None] = []
        for c in claims:
            unit = nodes.get(c.unit)
            src = nodes.get(unit.source) if isinstance(unit, Unit) else None
            if isinstance(src, SourceItem):
                if src not in sources:
                    sources.append(src)
                claim_sources.append(sources.index(src) + 1)
            else:
                claim_sources.append(None)
        earlier = {claim for r in reports if r.run_date < log.run_date for claim in r.claims}
        today = set(log.claims)
        known = [
            k.text
            for i in question.evidence
            if i in earlier and i not in today and isinstance(k := nodes.get(i), Claim)
        ]
        out.append(
            BenchCase(
                id=_case_id(slug, question.id, [c.id for c in claims]),
                split="dev",
                line_slug=slug,
                line_name=line_name,
                vocabulary=tuple(vocabulary),
                question_title=question.title,
                question_brief=question.brief,
                run_date=log.run_date,
                claims=tuple(
                    BenchClaim(text=c.text, source=s)
                    for c, s in zip(claims, claim_sources, strict=True)
                ),
                known=tuple(known),
                sources=tuple(
                    BenchSource(title=s.title, url=s.url, excerpt=s.text[:EXCERPT_CHARS])
                    for s in sources
                ),
                baseline=log.text,
            )
        )
    return out


def split_of(case_id: str) -> Split:
    """From the id alone, so a case never moves between dev and holdout when later exports
    add cases (an index-based split would: code review) — about 1 in HOLDOUT_EVERY held out."""
    return "holdout" if int(case_id, 16) % HOLDOUT_EVERY == 0 else "dev"


def split_cases(cases: Sequence[BenchCase]) -> list[BenchCase]:
    """Dedup by id (the same question-day exported from several stores) and set the split."""
    unique = {c.id: c for c in cases}
    return sorted(
        (c.model_copy(update={"split": split_of(c.id)}) for c in unique.values()),
        key=lambda c: (c.line_slug, c.id),
    )


def export(
    roots: Sequence[Path], contexts: Mapping[str, LineContext], out: Path
) -> list[BenchCase]:
    """Cases from every line partition of every store root, written to `out/cases/`."""
    found: list[BenchCase] = []
    for root in roots:
        for path in sorted((root / "lines").glob("*.jsonld")):
            slug = path.stem
            ctx = contexts.get(slug)
            found += cases_from_nodes(
                slug,
                GraphStore(root).line(slug).load(),
                line_name=ctx.line.name if ctx else slug,
                vocabulary=ctx.vocabulary if ctx else (),
            )
    cases = split_cases(found)
    directory = out / "cases"
    directory.mkdir(parents=True, exist_ok=True)
    for c in cases:
        (directory / f"{c.id}.json").write_text(c.model_dump_json(indent=2), encoding="utf-8")
    return cases


def load_cases(bench: Path, split: Split | Literal["all"] = "all") -> list[BenchCase]:
    cases = [
        BenchCase.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted((bench / "cases").glob("*.json"))
    ]
    return [c for c in cases if split == "all" or c.split == split]


# --- bench ----------------------------------------------------------------------------------


def gates(prose: str, n_claims: int) -> tuple[str, ...]:
    """The code gates. Invalid [n] were already dropped by check_citations, so what is left
    to check is where citations and the inference mark sit."""
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    failed: list[str] = []
    marked = [i for i, p in enumerate(paragraphs) if p.startswith(INFERENCE_MARK)]
    if len(marked) != 1 or marked[0] != len(paragraphs) - 1:
        failed.append("推論段落が最後に 1 つではない")
    elif re.search(r"\[\d+\]", paragraphs[-1]):
        failed.append("推論段落に [n] がある")
    for p in paragraphs[: len(paragraphs) - 1 if marked else len(paragraphs)]:
        if p.strip() != NO_DIRECT_EVIDENCE and not re.search(r"\[\d+\]", p):
            failed.append("引用の無い根拠段落がある")
            break
    if n_claims and not re.search(r"\[\d+\]", prose):
        failed.append("引用が 1 つも無い")
    return tuple(failed)


def bench_model(
    name: str, http: httpx2.AsyncClient, *, api_key: str, thinking: bool
) -> OpenAIChatModel:
    """Any DashScope model id — the bench tries models a run does not pin (each has its own
    free quota). Same profile and thinking switch as qwen.client.qwen_model."""
    provider = AlibabaProvider(api_key=api_key, base_url=DASHSCOPE_BASE_URL, http_client=http)
    return OpenAIChatModel(
        name,
        provider=provider,
        profile=_native_json_schema,
        settings=THINKING if thinking else NO_THINKING,
    )


def case_context(case: BenchCase) -> tuple[LineContext, Question]:
    line = Line(
        id=f"https://github.com/shimo4228/{case.line_slug}",
        slug=case.line_slug,
        name=case.line_name,
        adapters=("arxiv",),
    )
    question = Question.new(
        line=line.id,
        slug="bench",
        version=1,
        title=case.question_title,
        brief=case.question_brief,
        opened_at=datetime.now(UTC),
    )
    return LineContext(line=line, vocabulary=case.vocabulary or (case.line_name,)), question


async def draft(
    case: BenchCase, variant: Variant, model: OpenAIChatModel, meter: GenerationMeter
) -> Draft:
    ctx, question = case_context(case)
    claims = [c.text for c in case.claims]
    thick = variant.sources and bool(case.sources)
    result = await write_prose(
        model,
        ctx,
        question,
        claims,
        feedback=None,
        meter=meter,
        timeout_s=PROSE_TIMEOUT_S,
        evidence_set=list(case.known) or None,
        instructions=variant.instructions,
        sources=[dict(s.model_dump()) for s in case.sources] if thick else None,
        claim_sources=[c.source or 0 for c in case.claims] if thick else None,
    )
    prose = result.prose
    return Draft(
        case=case.id,
        variant=variant.name,
        prose=prose,
        failure=result.failure,
        seconds=result.seconds,
        chars=len(prose or ""),
        gates=gates(prose, len(claims)) if prose else ("生成失敗",),
    )


def write_draft(bench: Path, d: Draft) -> Path:
    path = bench / "drafts" / d.variant / f"{d.case}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(d.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_drafts(bench: Path, variant: str) -> dict[str, Draft]:
    return {
        (d := Draft.model_validate_json(p.read_text(encoding="utf-8"))).case: d
        for p in sorted((bench / "drafts" / variant).glob("*.json"))
    }


# --- pairs ----------------------------------------------------------------------------------

AXIS_HEADING: Final = re.compile(r"^### (.+)$", re.M)


def rubric_parts(rubric: str) -> tuple[str, list[str], str]:
    """docs/prose-rubric.md split at its markers: judge preamble, the quality axes (one
    `### ` block each, shuffled per pair file), and the closing protocol."""
    head, rest = rubric.split("<!-- axes -->", 1)
    axes_text, tail = rest.split("<!-- /axes -->", 1)
    starts = [m.start() for m in AXIS_HEADING.finditer(axes_text)]
    axes = [
        axes_text[a:b].strip() for a, b in zip(starts, [*starts[1:], len(axes_text)], strict=True)
    ]
    return head.strip(), axes, tail.strip()


def materials(case: BenchCase) -> str:
    lines = [
        f"研究ライン: {case.line_name}",
        f"問い: {case.question_title}",
        f"問いの背景: {case.question_brief}" if case.question_brief else "",
        "",
        "今日の claim(原文。本文の [n] はこの番号):",
        *(
            f"[{i}] {c.text}" + (f"  (出典 S{c.source})" if c.source else "")
            for i, c in enumerate(case.claims, start=1)
        ),
        "",
        "既知の evidence(以前に分かっていたこと):" if case.known else "既知の evidence: なし",
        *(f"- {k}" for k in case.known),
        "",
        "出典(タイトルと抜粋。本文の書き手にこれが渡ったとは限らない):",
        *(
            f"S{i}. {s.title} — {s.url}\n    {s.excerpt}"
            for i, s in enumerate(case.sources, start=1)
        ),
    ]
    return "\n".join(lines)


def make_pairs(
    bench: Path, a: str, b: str, rubric: str, *, split: Split | Literal["all"], seed: int = 0
) -> Path:
    """Two files per case (A first, then B first) with the axes in a different random order
    each; key.json maps every file's 草稿X / 草稿Y to its variant. Drafts that failed a code
    gate still go in — the judge sees the gate result as a fact line."""
    head, axes, tail = rubric_parts(rubric)
    da, db = load_drafts(bench, a), load_drafts(bench, b)
    out = bench / "pairs" / f"{a}__vs__{b}"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(f"{a}|{b}|{seed}")
    key: dict[str, dict[str, str]] = {}
    for case in load_cases(bench, split):
        if case.id not in da or case.id not in db:
            continue
        for order, (x, y) in enumerate(((da[case.id], db[case.id]), (db[case.id], da[case.id])), 1):
            shuffled = axes[:]
            rng.shuffle(shuffled)
            name = f"{case.id}__{order}"
            body = "\n\n".join(
                [
                    head,
                    "## 評価軸(この順に判定する)",
                    *shuffled,
                    tail,
                    "## 材料",
                    materials(case),
                    "## 草稿X",
                    _shown(x),
                    "## 草稿Y",
                    _shown(y),
                ]
            )
            (out / f"{name}.md").write_text(body + "\n", encoding="utf-8")
            key[name] = {"X": x.variant, "Y": y.variant, "case": case.id}
    (out / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _shown(d: Draft) -> str:
    gate = "コード検査: 通過" if not d.gates else f"コード検査: 不合格({' / '.join(d.gates)})"
    return f"{gate}\n\n{d.prose or '(生成なし)'}"


# --- tally ----------------------------------------------------------------------------------


class AxisVerdict(Value):
    winner: Literal["X", "Y", "tie"]
    quote_x: str = ""
    quote_y: str = ""
    why: str = ""


class Verdict(Value):
    gate: dict[str, Literal["pass", "fail"]]
    gate_why: str = ""
    axes: dict[str, AxisVerdict]
    overall: AxisVerdict


def tally(pairs: Path, a: str, b: str, verdicts: Path | None = None) -> list[str]:
    """Per case, an axis is won only when both orders pick the same variant (else a tie);
    a gate failure in either order loses the case's overall. Lines for the terminal."""
    key: dict[str, dict[str, str]] = json.loads((pairs / "key.json").read_text(encoding="utf-8"))
    per_case: dict[str, list[tuple[dict[str, str], Verdict]]] = {}
    for name, k in key.items():
        path = (verdicts or pairs / "verdicts") / f"{name}.json"
        if path.is_file():
            per_case.setdefault(k["case"], []).append(
                (k, Verdict.model_validate_json(path.read_text(encoding="utf-8")))
            )
    axes: dict[str, dict[str, int]] = {}
    gate_fail = {a: 0, b: 0}

    def to_variant(k: dict[str, str], w: str) -> str:
        return k[w] if w in ("X", "Y") else "tie"

    for runs in per_case.values():
        if len(runs) < 2:
            continue
        failed = {
            k[slot] for k, v in runs for slot, g in v.gate.items() if g == "fail" and slot in k
        }
        for f in failed:
            gate_fail[f] = gate_fail.get(f, 0) + 1
        names = {n for _, v in runs for n in v.axes} | {"総合"}
        for axis in names:
            given = [(k, v.overall if axis == "総合" else v.axes.get(axis)) for k, v in runs]
            # Won only when every order gave a verdict and they agree (code review: an axis
            # one order left out used to be decided by the other order alone).
            picks = {to_variant(k, av.winner) for k, av in given if av is not None}
            complete = all(av is not None for _, av in given)
            winner = picks.pop() if complete and len(picks) == 1 else "tie"
            if axis == "総合" and failed:
                # the rubric: a gate failure loses the overall; both failing is a tie
                winner = ({a, b} - failed).pop() if len(failed) == 1 else "tie"
            axes.setdefault(axis, {a: 0, b: 0, "tie": 0})[winner] += 1
    lines = [f"cases judged in both orders: {sum(1 for r in per_case.values() if len(r) >= 2)}"]
    lines += [f"gate failures: {a} {gate_fail[a]} / {b} {gate_fail[b]}"]
    for axis, c in sorted(axes.items(), key=lambda kv: kv[0] != "総合"):
        lines.append(f"{axis}: {a} {c[a]} / {b} {c[b]} / tie {c['tie']}")
    return lines


def lengths(bench: Path, variant: str) -> str:
    d = load_drafts(bench, variant).values()
    chars = sorted(x.chars for x in d if x.prose)
    if not chars:
        return f"{variant}: no drafts"
    return f"{variant}: {len(chars)} drafts, chars min {chars[0]} / median {chars[len(chars) // 2]} / max {chars[-1]}"


async def run_bench(
    bench: Path,
    variant: Variant,
    *,
    http: httpx2.AsyncClient,
    api_key: str,
    split: Split | Literal["all"],
    concurrency: int,
) -> list[str]:
    """Draft every case of `split` with `variant`; lines for the terminal. A case already
    drafted by this variant is skipped (drafts are the expensive part: free quota)."""
    model = bench_model(variant.model, http, api_key=api_key, thinking=variant.thinking)
    meter = GenerationMeter()
    done = load_drafts(bench, variant.name)
    todo = [c for c in load_cases(bench, split) if c.id not in done]
    slots = asyncio.Semaphore(concurrency)

    async def one(case: BenchCase) -> Draft:
        async with slots:
            return await draft(case, variant, model, meter)

    drafts = await asyncio.gather(*(one(c) for c in todo))
    for d in drafts:
        write_draft(bench, d)
    failed = [d for d in drafts if d.gates]
    return [
        f"{variant.name}: {len(drafts)} drafted, {len(done)} already there",
        f"tokens in {meter.input_tokens} / out {meter.output_tokens}",
        *(f"gate: {d.case} {' / '.join(d.gates)}" for d in failed),
        lengths(bench, variant.name),
    ]
