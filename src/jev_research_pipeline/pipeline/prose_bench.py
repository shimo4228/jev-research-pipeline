"""Prose bench: frozen question-day inputs, prompt/model variants, blind pairs for a judge.

The one generation site left is the prose (design "Authored queries"), and the author's
verdict on it is "weak". This is the loop that improves it without touching a run:

    jrp prose export   question-days with prose, from one or more stores → frozen cases
    jrp prose bench    one variant (prompt file x model x thinking x material) over the
                       cases → drafts, each with the code gates (facts, not taste)
    jrp prose read     one or more variants → a blind reading file for the author
                       (the ground truth for readability) and a key beside it
    jrp prose gate     one variant → one file per draft for the fidelity judge; with
                       --verdicts, the pass / fail summary of the judge's verdicts

Roles (skill author-calibrated-eval): the author reads for readability; a fresh-context
Opus judge (.claude/agents/prose-judge.md) checks fidelity only, one draft at a time, with
binary checks and a pass / fail verdict (docs/prose-rubric.md) — an Opus judge asked for
readability picked the more informative draft the author found hard to read (2026-09-23);
code checks form. Dev time only; no run calls Claude. Everything lives under <JRP_STORE_DIR>/prose_bench/, never in the repo: cases
carry verbatim third-party text (claims, source excerpts), and the repo is public.

Cases are split by their id alone (about one in three held out), so a case never changes
side when later exports add cases. Variants are tuned on `dev` and accepted only if `holdout` does not get worse.
"""

import asyncio
import hashlib
import json
import random
import re
from collections.abc import Collection, Mapping, Sequence
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
    SOURCE_EXCERPT_CHARS,
    write_prose,
)
from jev_research_pipeline.store import GraphStore

BENCH_DIR: Final = "prose_bench"
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
    check: str | None = None
    """Instructions for a second pass by the same model that verifies the draft against
    the claims and returns a corrected text (self-check). None = one pass."""


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
                    BenchSource(title=s.title, url=s.url, excerpt=s.text[:SOURCE_EXCERPT_CHARS])
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
        if not _cited_or_framing(p):
            failed.append("引用の無い根拠段落がある")
            break
    if n_claims and not re.search(r"\[\d+\]", prose):
        failed.append("引用が 1 つも無い")
    return tuple(failed)


FRAMING_MAX_CHARS: Final = 120


def _cited_or_framing(paragraph: str) -> bool:
    """An evidence paragraph cites a claim [n] or a source excerpt (S1) — or is a short
    framing sentence with no figure in it ("Jev の名は出てこないが、以下は…"), which states
    no fact to cite. The fixed NO_DIRECT_EVIDENCE sentence is one of those."""
    if re.search(r"\[\d+\]|\(S\d+\)", paragraph) or paragraph == NO_DIRECT_EVIDENCE:
        return True
    return len(paragraph) <= FRAMING_MAX_CHARS and not re.search(r"\d", paragraph)


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
    seconds = result.seconds
    if variant.check and prose:
        checked = await write_prose(
            model,
            ctx,
            question,
            claims,
            feedback=None,
            meter=meter,
            timeout_s=PROSE_TIMEOUT_S,
            evidence_set=list(case.known) or None,
            instructions=variant.check,
            sources=[dict(s.model_dump()) for s in case.sources] if thick else None,
            claim_sources=[c.source or 0 for c in case.claims] if thick else None,
            draft=prose,
        )
        seconds += checked.seconds
        prose = checked.prose or prose  # a failed check keeps the first draft
    return Draft(
        case=case.id,
        variant=variant.name,
        prose=prose,
        failure=result.failure,
        seconds=seconds,
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


# --- gate: the LLM judge checks fidelity, one draft at a time -------------------------------


def materials(case: BenchCase) -> str:
    """What the writer was given, as the judge and the author see it: the same excerpts."""
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
        *(f"S{i}. {s.title} — {s.url}\n    {s.excerpt}" for i, s in enumerate(case.sources, 1)),
    ]
    return "\n".join(lines)


def _selected(
    bench: Path, variant: str, split: Split | Literal["all"], only: Collection[str] | None
):
    drafts = load_drafts(bench, variant)
    return [
        (case, drafts[case.id])
        for case in load_cases(bench, split)
        if case.id in drafts and (only is None or case.id in only)
    ]


def gate_files(
    bench: Path,
    variant: str,
    rubric: str,
    *,
    split: Split | Literal["all"],
    only: Collection[str] | None = None,
) -> tuple[Path, int]:
    """One file per draft — the rubric, the materials, the draft — for a fresh-context judge
    that writes one GateVerdict. The code gates are re-run first and shown as a fact line: a
    check corrected after the draft was stored must reach the judge."""
    out = bench / "gate" / variant
    out.mkdir(parents=True, exist_ok=True)
    selected = _selected(bench, variant, split, only)
    for case, d in selected:
        failed = gates(d.prose, len(case.claims)) if d.prose else d.gates
        code = "コード検査: 通過" if not failed else f"コード検査: 不合格({' / '.join(failed)})"
        body = "\n\n".join(
            [rubric.strip(), "## 材料", materials(case), "## 草稿", code, d.prose or "(生成なし)"]
        )
        (out / f"{case.id}.md").write_text(body + "\n", encoding="utf-8")
    return out, len(selected)


class Check(Value):
    question: str
    answer: Literal["Yes", "No"]
    detail: str = ""


class GateVerdict(Value):
    """docs/prose-rubric.md's output: binary checks as evidence, one named verdict, no score
    (skill llm-as-judge)."""

    verdict: Literal["pass", "fail"]
    evidence: tuple[Check, ...] = ()
    reason: str = ""


def gate_summary(bench: Path, variant: str, verdicts: Path | None = None) -> list[str]:
    """Lines for the terminal: pass / fail counts, then every failing draft with its reason."""
    directory = verdicts or bench / "gate" / variant / "verdicts"
    judged = {
        path.stem: GateVerdict.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }
    failed = {k: v for k, v in judged.items() if v.verdict == "fail"}
    return [
        f"{variant}: pass {len(judged) - len(failed)} / fail {len(failed)} / judged {len(judged)}",
        *(f"fail: {k} {' '.join(v.reason.split())[:200]}" for k, v in failed.items()),
    ]


# --- read: the author reads the drafts blind ------------------------------------------------


def read_file(
    bench: Path,
    variants: Sequence[str],
    out: Path,
    *,
    split: Split | Literal["all"] = "all",
    only: Collection[str] | None = None,
    seed: str = "read",
) -> tuple[Path, int]:
    """The author's reading file: per case, the variants' drafts under shuffled letters (one
    variant = one draft), the claims folded above them, and the two questions to answer. The
    letter -> variant key goes to <out>.key.json; the reading file never names a variant."""
    by_variant = {v: load_drafts(bench, v) for v in variants}
    cases = [
        c
        for c in load_cases(bench, split)
        if all(c.id in d for d in by_variant.values()) and (only is None or c.id in only)
    ]
    ask = (
        "「一番良いのはどれか」「なぜか(一言)」"
        if len(variants) > 1
        else "「読めるか」「どこで止まったか」"
    )
    lines = [
        "# 読み比べ",
        "",
        f"各 case について {ask} を書いてください。版の名前は伏せてあります。",
        "",
    ]
    key: dict[str, dict[str, str]] = {}
    for n, case in enumerate(cases, start=1):
        order = list(variants)
        random.Random(f"{seed}|{case.id}").shuffle(order)
        letters = [chr(ord("A") + i) for i in range(len(order))]
        key[f"case{n}"] = {"id": case.id, **dict(zip(letters, order, strict=True))}
        lines += [
            f"## case {n}: {case.question_title}",
            "",
            f"> [!note]- 材料(claim {len(case.claims)} 件)",
        ]
        for i, c in enumerate(case.claims, start=1):
            source = case.sources[c.source - 1].title if c.source else ""
            lines.append(f"> [{i}] {c.text}" + (f" — {source}" if source else "") + "  ")
        lines.append("")
        for letter, v in zip(letters, order, strict=True):
            prose = by_variant[v][case.id].prose or "(生成なし)"
            lines += ([f"### {letter}", ""] if len(order) > 1 else []) + [prose, ""]
        lines += ["**答え:**  ", "", "---", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out, len(cases)


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
    only: Collection[str] | None = None,
) -> list[str]:
    """Draft every case of `split` with `variant`; lines for the terminal. A case already
    drafted by this variant is skipped (drafts are the expensive part: free quota)."""
    model = bench_model(variant.model, http, api_key=api_key, thinking=variant.thinking)
    meter = GenerationMeter()
    done = load_drafts(bench, variant.name)
    todo = [
        c for c in load_cases(bench, split) if c.id not in done and (only is None or c.id in only)
    ]
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
