"""The generation site: Japanese prose for one open question (the model JRP_PROSE_MODEL
names, generation.client), and the rendering ladder that maps onto Report.rendering
(decision 8, rubric-eval row):

    write → rubric_report accept → "prose"
          → reject → rewrite once with feedback → accept → "rewritten"
                                                → otherwise → "template"
    synthesis failure, or rubric unjudged (cannot verify) → "template"

"template" means prose is None; the step-7 renderer then writes the template report.
One call = one question that moved today: what the day's claims advance or overturn for
it. Inference is allowed — the first live run's prose was a paraphrase of the claims
because it was forbidden — but it has to sit in its own paragraph opening with
INFERENCE_MARK, so the rubric's `grounded` axis and the reader can both tell it from the
evidence paragraphs.

Claims are quoted external text: the prompt fences them as data (<claims>) and tells the
model not to follow instructions inside them. Inside the fence they are a JSON array
(json.dumps escapes `<`, `>` and newlines), so claim text can neither close the fence
nor forge a claim number. Citations are checked by code, never trusted: check_citations()
drops every [n] that does not name a claim of this call.
"""

import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from importlib.resources import files
from typing import Final, Literal

from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from jev_research_pipeline.jev.context import LineContext
from jev_research_pipeline.model import Decision, Question
from jev_research_pipeline.model.jsonld import Value
from jev_research_pipeline.note_text import DEFAULT_LANG, LANGS, Lang, Msg

from .client import GenerationMeter, auth_failure

INFERENCE_MARKS: Final[Mapping[Lang, str]] = {
    "ja": "【推論】",
    "en": "[Inference]",
    "zh": "【推论】",
}
"""A paragraph that goes beyond the claims opens with its language's mark and nothing else
does. Any language's mark is recognized, so a note's language never decides what is checked."""
INFERENCE_MARK: Final = INFERENCE_MARKS["ja"]

NO_DIRECT_EVIDENCE: Final = "この問いの対象への直接の証拠は無い。"
"""Written verbatim when the claims are about something else (author mandate 2026-09-23);
it is the pipeline's own statement, not a claim's, so the fidelity check leaves it out."""

STUDY_NAME_LINE: Final = re.compile(r"\s*\*\*[^*\n]+\*\*\s*$")
"""A paragraph that is only a study's bold name line (v10 on: "**EvalMem**")."""

SOURCE_EXCERPT_CHARS: Final = 1500
"""Per source, sent with the claims: enough of an abstract to say what the work did."""


def _prompt(name: str) -> str:
    return (files(__package__) / "prompts" / name).read_text(encoding="utf-8").rstrip("\n")


PROSE_PROMPTS: Final[Mapping[Lang, str]] = {lang: _prompt(f"prose.{lang}.md") for lang in LANGS}
"""The production prose prompt per note language, shipped in the package (generation/
prompts/). Each is the text of the bench prompt it was chosen as (tests/test_prose.py pins
it): ja = bench/prose/prompts/v15.md, en = en2.md, zh = zh1.md (design "Prose in English",
"Prose in Chinese"). en and zh were accepted on the bench's proxies alone: the author reads
neither (2026-10-01)."""
CHECK_PROMPTS: Final[Mapping[Lang, str]] = {lang: _prompt(f"check.{lang}.md") for lang in LANGS}
"""The self-check pass per language: ja = check9.md, en = en-check1.md, zh = zh-check1.md."""

INSTRUCTIONS: Final = PROSE_PROMPTS["ja"]
"""The ja prose prompt tuned on the prose bench (bench/prose/prompts/v15.md; design "Prose
bench on claude -p"): explain today's studies to a reader who has not read them — a lead that
says each study's finding with its conditions and cites; per study a bold name line, then one
to two paragraphs (600-1,000 chars) of problem, what they did, what they found, the room
spent on premises and glossing, never on more facts; numbers copied exactly with their
comparator in the same sentence; background only from the excerpt; one final inference
paragraph; the plain である register. Chosen by the author's blind read on Claude Opus
(5 of 5, 2026-10-01); on gpt-6-luna the same prompt did not improve the fidelity cutoff."""

CHECK_INSTRUCTIONS: Final = CHECK_PROMPTS["ja"]
"""The self-check pass (bench/prose/prompts/check9.md): the same model re-reads its draft
against the claims and excerpts and fixes only factual slips — numbers and comparators,
dropped hedges, intent written as result, subject swaps, citations (one on every factual
paragraph), a lead that merges studies — and turns polite-register sentences into である."""

_CITATION_RE: Final = re.compile(r"\[(\d+)\]")
_GAP_RE: Final = re.compile(r"[ \t]{2,}")
_BEFORE_PUNCTUATION_RE: Final = re.compile("[ \t]+([\u3001\u3002\uff09\uff0c\uff0e)\\]])")


def check_citations(text: str, n_claims: int) -> tuple[str, tuple[int, ...]]:
    """Drop every [n] that does not name a claim of this call, and report the ones dropped.

    Citation binding is deterministic (search-first synthesis): the model proposes the
    number, code decides whether it exists. A prose that cites claim 9 of 4 loses the
    citation rather than the reader's trust."""
    invalid: list[int] = []

    def replace(match: re.Match[str]) -> str:
        n = int(match.group(1))
        if 1 <= n <= n_claims:
            return match.group(0)
        invalid.append(n)
        return ""

    cleaned = _CITATION_RE.sub(replace, text)
    # Removing a citation leaves a hole: a doubled space, or a space before the sentence's
    # own punctuation. Tidy exactly those, so the paragraph reads as if it was never there.
    cleaned = _GAP_RE.sub(" ", cleaned)
    cleaned = _BEFORE_PUNCTUATION_RE.sub(r"\1", cleaned)
    return cleaned.strip(), tuple(invalid)


def is_inference(paragraph: str) -> bool:
    return paragraph.lstrip().startswith(tuple(INFERENCE_MARKS.values()))


def inference_paragraphs(text: str) -> tuple[str, ...]:
    """The paragraphs the model marked as going beyond the claims."""
    return tuple(p for p in text.split("\n\n") if is_inference(p))


def evidence_text(text: str) -> str:
    """Everything but the marked inference — what `grounded` is judged on."""
    return "\n\n".join(p for p in text.split("\n\n") if not is_inference(p))


LINE_LABEL: Final = Msg("研究ライン: {v}", "Research line: {v}", "研究方向: {v}")
VOCABULARY_LABEL: Final = Msg("語彙: {v}", "Vocabulary: {v}", "词汇: {v}")
QUESTION_LABEL: Final = Msg("問い: {v}", "Question: {v}", "问题: {v}")
BRIEF_LABEL: Final = Msg("問いの背景: {v}", "Background of the question: {v}", "问题背景: {v}")
FEEDBACK_LABEL: Final = Msg(
    "前回の草稿への指摘: {v}", "Feedback on the previous draft: {v}", "对上一稿的意见: {v}"
)


PROSE_TIMEOUT_S: Final = 900.0
"""One prose call may take minutes: 37 claims hit the 30s client timeout on the first
live run (2026-09-22) and died after 92s of retries. ModelSettings.timeout is sent per
request and overrides the shared client's timeout, so only this call gets the long one."""
PROSE_TIMEOUT_ENV: Final = "JRP_PROSE_TIMEOUT_S"


def prose_timeout_s(env: Mapping[str, str]) -> float:
    """A mis-set env var must not cost the run: anything unparseable or <= 0 is ignored."""
    try:
        seconds = float(env.get(PROSE_TIMEOUT_ENV, ""))
    except ValueError:
        return PROSE_TIMEOUT_S
    return seconds if seconds > 0 else PROSE_TIMEOUT_S


PROSE_THINKING_ENV: Final = "JRP_PROSE_THINKING"
PROSE_THINKING: Final = "always"
"""off = never think; rewrite = the second draft only (the one after a rubric or fidelity
rejection); always = every draft. The backend maps it (generation.client: DashScope's
enable_thinking, the Codex model's reasoning effort). always, from the A/B of 2026-09-23 on
qwen3.8-max (docs/pilot-log.md):
thinking won 6 of 7 blind comparisons and had no fidelity flag; off put conclusions into
evidence paragraphs twice. It costs time (79-496 s a draft, contended) — hence the 900 s (≈ 1.8x the slowest seen)
prose timeout."""
type ProseThinking = Literal["off", "rewrite", "always"]


def prose_thinking(env: Mapping[str, str]) -> ProseThinking:
    raw = env.get(PROSE_THINKING_ENV, PROSE_THINKING)
    if raw == "off":
        return "off"
    if raw == "rewrite":
        return "rewrite"
    return "always"


def prose_agent(
    model: Model, *, timeout_s: float, instructions: str = INSTRUCTIONS
) -> Agent[None, str]:
    """`instructions` is overridden only by the prose bench (pipeline.prose_bench), which
    compares prompt variants on frozen inputs; a run always uses INSTRUCTIONS."""
    return Agent(model, instructions=instructions, model_settings=ModelSettings(timeout=timeout_s))


class ProseResult(Value):
    prose: str | None
    failure: str | None
    seconds: float = 0.0
    """Wall time of the generation call — the first live run's 30s timeout was invisible
    in the report until this reached the operations section."""
    invalid_citations: tuple[int, ...] = ()
    """[n]s the model wrote that name no claim of this call; dropped from the text."""
    auth: bool = False
    """The failure was the writer refusing its credentials (generation.client.auth_failure)."""


class Rendering(Value):
    rendering: Literal["prose", "rewritten", "template"]
    prose: str | None
    rubric: tuple[Decision, ...]
    """rubric_report decisions, one per evaluated draft (0-2)."""
    drafts: tuple[ProseResult, ...] = ()
    """Each generation attempt with its failure reason and wall time (operations section)."""


def as_data(value: object) -> str:
    """JSON for the prompt, with `<` and `>` escaped so the text inside can neither close
    the data fence nor open another one. Every piece of third-party text in the prompt goes
    through here — the claims and the evidence set are both source-derived."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def user_prompt(
    ctx: LineContext,
    question: Question,
    claims: list[str],
    feedback: str | None,
    *,
    evidence_set: list[str] | None = None,
    sources: list[dict[str, object]] | None = None,
    claim_sources: list[int] | None = None,
    draft: str | None = None,
    lang: Lang = DEFAULT_LANG,
) -> str:
    """`sources` (title / excerpt / url per source) and `claim_sources` (the 1-based source
    of each claim) are the thicker material the prose bench tuned; a run sends both (pipeline.run).
    `lang` words the labels; the data inside <claims> is as fetched."""
    payload: dict[str, object] = {
        "claims": [
            {"n": i, "text": text}
            | (
                {"source": f"S{claim_sources[i - 1]}"}
                if claim_sources is not None and claim_sources[i - 1]
                else {}
            )
            for i, text in enumerate(claims, start=1)
        ]
    }
    if evidence_set:
        payload["known"] = list(evidence_set)
    if sources:
        # "S1", not 1: a numeric source id got cited as a claim number (first bench judge
        # round, 2026-09-23 — [3] written for claim [1] throughout a draft)
        payload["sources"] = [{"id": f"S{i}", **src} for i, src in enumerate(sources, start=1)]
    parts = [
        LINE_LABEL(lang, v=ctx.line.name),
        VOCABULARY_LABEL(lang, v=", ".join(ctx.vocabulary)),
        QUESTION_LABEL(lang, v=question.title),
    ]
    if question.brief:
        parts.append(BRIEF_LABEL(lang, v=question.brief))
    parts.append(f"<claims>\n{as_data(payload)}\n</claims>")
    if draft:
        # the bench's self-check pass: the draft to verify against the claims above
        parts.append(f"<draft>\n{draft}\n</draft>")
    if feedback:
        parts.append(FEEDBACK_LABEL(lang, v=feedback))
    return "\n\n".join(parts)


def _since(started: float) -> float:
    return round(time.perf_counter() - started, 3)


async def write_prose(
    model: Model,
    ctx: LineContext,
    question: Question,
    claims: list[str],
    *,
    feedback: str | None,
    meter: GenerationMeter,
    timeout_s: float = PROSE_TIMEOUT_S,
    evidence_set: list[str] | None = None,
    instructions: str = INSTRUCTIONS,
    sources: list[dict[str, object]] | None = None,
    claim_sources: list[int] | None = None,
    draft: str | None = None,
    lang: Lang = DEFAULT_LANG,
) -> ProseResult:
    """`claims` in reading order. Never raises for model trouble; every [n] it writes is
    checked against `claims` before the text leaves this function."""
    agent = prose_agent(model, timeout_s=timeout_s, instructions=instructions)
    usage = RunUsage()  # filled as the run goes, so failed runs are metered too
    started = time.perf_counter()
    try:
        result = await agent.run(
            user_prompt(
                ctx,
                question,
                claims,
                feedback,
                evidence_set=evidence_set,
                sources=sources,
                claim_sources=claim_sources,
                draft=draft,
                lang=lang,
            ),
            usage=usage,
        )
    except AgentRunError as e:
        return ProseResult(
            prose=None,
            failure=f"{type(e).__name__}: {e}"[:200],
            seconds=_since(started),
            auth=auth_failure(e),
        )
    finally:
        meter.add(usage)
    text, invalid = check_citations(result.output.strip(), len(claims))
    return ProseResult(
        prose=text or None,
        failure=None if text else "empty",
        seconds=_since(started),
        invalid_citations=invalid,
    )


REWRITE_FEEDBACKS: Final = Msg(
    "読みやすさ・段落のつながり・claim に無い記述のいずれかが基準に届かなかった。"
    f"claim に無い記述は削るか「{INFERENCE_MARKS['ja']}」段落に移し、段落同士をつなげて書き直す。",
    "Readability, the links between paragraphs, or statements the claims do not make fell "
    "short. Remove what the claims do not say or move it to the "
    f"{INFERENCE_MARKS['en']} paragraph, and rewrite with the paragraphs connected.",
    "可读性、段落之间的衔接，或 claim 中没有的表述，有一项未达标准。删掉 claim 中没有的表述，"
    f"或移到「{INFERENCE_MARKS['zh']}」段落，并把段落衔接起来重写。",
)
REWRITE_FEEDBACK: Final = REWRITE_FEEDBACKS.ja


FIDELITY_FEEDBACKS: Final = Msg(
    "研究の段落に、claim と抜粋の範囲を超えた言い換えがあった (問いの語で研究の対象を"
    "置き換えている、claim に無い属性や結論を足している)。研究の対象と限定をそのまま保ち、"
    f"問いへのつながりは「{INFERENCE_MARKS['ja']}」段落でだけ書いて書き直す。",
    "A study paragraph paraphrased beyond what the claims and excerpts say (the question's "
    "terms put in place of the study's subject, an attribute or a conclusion the claims do "
    "not give). Keep the study's subject and hedges as they are, make the link to the "
    f"question only in the {INFERENCE_MARKS['en']} paragraph, and rewrite.",
    "研究段落中有超出 claim 和摘录范围的改写(用问题的说法替换了研究对象，或添加了 claim "
    "中没有的属性或结论)。保持研究对象和限定不变，与问题的联系只写在"
    f"「{INFERENCE_MARKS['zh']}」段落里，然后重写。",
)
FIDELITY_FEEDBACK: Final = FIDELITY_FEEDBACKS.ja


async def render(
    write: Callable[[str | None], Awaitable[ProseResult]],
    evaluate: Callable[[str], Awaitable[Decision]],
    lang: Lang = DEFAULT_LANG,
) -> Rendering:
    """The ladder. `write(feedback)` drafts; `evaluate(prose)` is the rubric_report decision."""
    rubric: list[Decision] = []
    drafts: list[ProseResult] = []
    feedback: str | None = None
    for rendering in ("prose", "rewritten"):
        draft = await write(feedback)
        drafts.append(draft)
        if draft.prose is None:
            break
        decision = await evaluate(draft.prose)
        rubric.append(decision)
        if decision.outcome == "accept":
            return Rendering(
                rendering=rendering, prose=draft.prose, rubric=tuple(rubric), drafts=tuple(drafts)
            )
        if decision.outcome == "unjudged":
            break  # cannot verify → never publish unverified prose
        feedback = (
            FIDELITY_FEEDBACKS.raw(lang)
            if "fidelity" in decision.policy
            else REWRITE_FEEDBACKS.raw(lang)
        )
    return Rendering(rendering="template", prose=None, rubric=tuple(rubric), drafts=tuple(drafts))
